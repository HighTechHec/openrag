import { create } from "zustand";
import type {
  FunctionCall,
  Message,
  TokenUsage,
} from "@/app/chat/_types/types";
import type { FilterInput } from "@/lib/filter-normalization";
import { buildSearchPayloadFilters } from "@/lib/filter-normalization";

interface SendMessageOptions {
  prompt: string;
  endpoint: string;
  previousResponseId?: string;
  filters?: FilterInput;
  filter_id?: string;
  limit?: number;
  scoreThreshold?: number;
}

interface ChatStreamCallbacks {
  onComplete?: (message: Message, responseId: string | null) => void;
  onError?: (error: Error) => void;
}

interface ChatStreamStore {
  streamingMessage: Message | null;
  isLoading: boolean;
  streamAbortController: AbortController | null;
  streamId: number;

  // Callbacks are stored in state so they can be updated dynamically
  // without losing the active stream reference across component remounts.
  callbacks: ChatStreamCallbacks;
  setCallbacks: (callbacks: ChatStreamCallbacks) => void;

  sendMessage: (options: SendMessageOptions) => Promise<Message | null>;
  abortStream: () => void;
  clearStreamingMessage: () => void;
}

export const useChatStreamStore = create<ChatStreamStore>((set, get) => ({
  streamingMessage: null,
  isLoading: false,
  streamAbortController: null,
  streamId: 0,
  callbacks: {},

  setCallbacks: (callbacks) => set({ callbacks }),

  clearStreamingMessage: () =>
    set({
      streamingMessage: null,
      isLoading: false,
      streamAbortController: null,
    }),

  abortStream: () => {
    const { streamAbortController } = get();
    if (streamAbortController) {
      streamAbortController.abort();
    }
    set({ streamingMessage: null, isLoading: false });
  },

  sendMessage: async ({
    prompt,
    endpoint,
    previousResponseId,
    filters,
    filter_id,
    limit = 10,
    scoreThreshold = 0,
  }) => {
    // Abort any existing stream before starting a new one
    get().abortStream();

    const controller = new AbortController();

    // Increment streamId
    set((state) => ({
      streamId: state.streamId + 1,
      streamAbortController: controller,
      isLoading: true,
    }));

    const thisStreamId = get().streamId;

    let timeoutId: NodeJS.Timeout | null = null;
    let hasReceivedData = false;

    try {
      // Set up timeout
      const startTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          if (!hasReceivedData) {
            console.error("Chat request timed out - no response received");
            controller.abort();
            throw new Error("Request timed out. The server is not responding.");
          }
        }, 60000);
      };

      startTimeout();

      const requestBody: any = {
        prompt,
        stream: true,
        limit,
        scoreThreshold,
      };

      if (previousResponseId) {
        requestBody.previous_response_id = previousResponseId;
      }

      if (filters) {
        const payloadFilters = buildSearchPayloadFilters(filters);
        if (payloadFilters) {
          requestBody.filters = payloadFilters;
        }
      }

      if (filter_id) {
        requestBody.filter_id = filter_id;
      }

      console.log("[chatStreamStore] Sending request:", {
        filter_id,
        requestBody,
        endpoint,
      });

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });

      if (timeoutId) clearTimeout(timeoutId);
      hasReceivedData = true;

      if (!response.ok) {
        const errorText = await response.text().catch(() => "Unknown error");
        throw new Error(`Server error (${response.status}): ${errorText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No reader available");
      }

      const decoder = new TextDecoder();
      let buffer = "";
      let currentContent = "";
      const currentFunctionCalls: FunctionCall[] = [];
      let newResponseId: string | null = null;
      let isError = false;
      let usageData: TokenUsage | undefined;

      if (!controller.signal.aborted && thisStreamId === get().streamId) {
        set({
          streamingMessage: {
            role: "assistant",
            content: "",
            timestamp: new Date(),
            isStreaming: true,
          },
        });
      }

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (controller.signal.aborted || thisStreamId !== get().streamId)
            break;
          if (done) break;

          hasReceivedData = true;
          if (timeoutId) clearTimeout(timeoutId);

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.trim()) {
              try {
                const chunk = JSON.parse(line);

                if (chunk.id) newResponseId = chunk.id;
                else if (chunk.response_id) newResponseId = chunk.response_id;

                // Handle OpenAI format
                if (chunk.object === "response.chunk" && chunk.delta) {
                  if (chunk.delta.function_call) {
                    if (chunk.delta.function_call.name) {
                      currentFunctionCalls.push({
                        name: chunk.delta.function_call.name,
                        arguments: undefined,
                        status: "pending",
                        argumentsString:
                          chunk.delta.function_call.arguments || "",
                      });
                    } else if (chunk.delta.function_call.arguments) {
                      const lastCall =
                        currentFunctionCalls[currentFunctionCalls.length - 1];
                      if (lastCall) {
                        lastCall.argumentsString =
                          (lastCall.argumentsString || "") +
                          chunk.delta.function_call.arguments;
                        if (lastCall.argumentsString.includes("}")) {
                          try {
                            lastCall.arguments = JSON.parse(
                              lastCall.argumentsString,
                            );
                            lastCall.status = "completed";
                          } catch (e) {}
                        }
                      }
                    }
                  } else if (
                    chunk.delta.tool_calls &&
                    Array.isArray(chunk.delta.tool_calls)
                  ) {
                    for (const toolCall of chunk.delta.tool_calls) {
                      if (toolCall.function) {
                        if (toolCall.function.name) {
                          currentFunctionCalls.push({
                            name: toolCall.function.name,
                            arguments: undefined,
                            status: "pending",
                            argumentsString: toolCall.function.arguments || "",
                          });
                        } else if (toolCall.function.arguments) {
                          const lastCall =
                            currentFunctionCalls[
                              currentFunctionCalls.length - 1
                            ];
                          if (lastCall) {
                            lastCall.argumentsString =
                              (lastCall.argumentsString || "") +
                              toolCall.function.arguments;
                            if (lastCall.argumentsString.includes("}")) {
                              try {
                                lastCall.arguments = JSON.parse(
                                  lastCall.argumentsString,
                                );
                                lastCall.status = "completed";
                              } catch (e) {}
                            }
                          }
                        }
                      }
                    }
                  } else if (chunk.delta.content) {
                    currentContent += chunk.delta.content;
                  }

                  if (chunk.delta.finish_reason) {
                    currentFunctionCalls.forEach((fc) => {
                      if (fc.status === "pending" && fc.argumentsString) {
                        try {
                          fc.arguments = JSON.parse(fc.argumentsString);
                          fc.status = "completed";
                        } catch (e) {
                          fc.arguments = { raw: fc.argumentsString };
                          fc.status = "error";
                        }
                      }
                    });
                  }
                }
                // Handle Realtime API function
                else if (
                  chunk.type === "response.output_item.added" &&
                  chunk.item?.type === "function_call"
                ) {
                  let existing =
                    currentFunctionCalls.find(
                      (fc) => fc.id === chunk.item.id,
                    ) ||
                    [...currentFunctionCalls]
                      .reverse()
                      .find(
                        (fc) =>
                          fc.status === "pending" &&
                          !fc.id &&
                          fc.name === (chunk.item.tool_name || chunk.item.name),
                      );
                  if (existing) {
                    existing.id = chunk.item.id;
                    existing.type = chunk.item.type;
                    existing.name =
                      chunk.item.tool_name || chunk.item.name || existing.name;
                    existing.arguments =
                      chunk.item.inputs || existing.arguments;
                  } else {
                    currentFunctionCalls.push({
                      name:
                        chunk.item.tool_name || chunk.item.name || "unknown",
                      arguments: chunk.item.inputs || undefined,
                      status: "pending",
                      argumentsString: "",
                      id: chunk.item.id,
                      type: chunk.item.type,
                    });
                  }
                }
                // Handle Realtime API tool call
                else if (
                  chunk.type === "response.output_item.added" &&
                  chunk.item?.type?.includes("_call") &&
                  chunk.item?.type !== "function_call"
                ) {
                  let existing =
                    currentFunctionCalls.find(
                      (fc) => fc.id === chunk.item.id,
                    ) ||
                    [...currentFunctionCalls]
                      .reverse()
                      .find(
                        (fc) =>
                          fc.status === "pending" &&
                          !fc.id &&
                          fc.name ===
                            (chunk.item.tool_name ||
                              chunk.item.name ||
                              chunk.item.type),
                      );
                  if (existing) {
                    existing.id = chunk.item.id;
                    existing.type = chunk.item.type;
                    existing.name =
                      chunk.item.tool_name ||
                      chunk.item.name ||
                      chunk.item.type ||
                      existing.name;
                    existing.arguments =
                      chunk.item.inputs || existing.arguments;
                  } else {
                    currentFunctionCalls.push({
                      name:
                        chunk.item.tool_name ||
                        chunk.item.name ||
                        chunk.item.type ||
                        "unknown",
                      arguments: chunk.item.inputs || {},
                      status: "pending" as const,
                      id: chunk.item.id,
                      type: chunk.item.type,
                    });
                  }
                }
                // Handle Realtime function done
                else if (
                  chunk.type === "response.output_item.done" &&
                  chunk.item?.type === "function_call"
                ) {
                  const fc = currentFunctionCalls.find(
                    (f) =>
                      f.id === chunk.item.id ||
                      f.name === chunk.item.tool_name ||
                      f.name === chunk.item.name,
                  );
                  if (fc) {
                    fc.status =
                      chunk.item.status === "completed" ? "completed" : "error";
                    fc.id = chunk.item.id;
                    fc.type = chunk.item.type;
                    fc.name =
                      chunk.item.tool_name || chunk.item.name || fc.name;
                    fc.arguments = chunk.item.inputs || fc.arguments;
                    if (chunk.item.results) fc.result = chunk.item.results;
                  }
                }
                // Handle Realtime tool call done
                else if (
                  chunk.type === "response.output_item.done" &&
                  chunk.item?.type?.includes("_call") &&
                  chunk.item?.type !== "function_call"
                ) {
                  const fc = currentFunctionCalls.find(
                    (f) =>
                      f.id === chunk.item.id ||
                      f.name === chunk.item.tool_name ||
                      f.name === chunk.item.name ||
                      f.name === chunk.item.type ||
                      f.name.includes(chunk.item.type.replace("_call", "")) ||
                      chunk.item.type.includes(f.name),
                  );
                  if (fc) {
                    fc.arguments = chunk.item.inputs || fc.arguments;
                    fc.status =
                      chunk.item.status === "completed" ? "completed" : "error";
                    fc.id = chunk.item.id;
                    fc.type = chunk.item.type;
                    if (chunk.item.results) fc.result = chunk.item.results;
                  } else {
                    currentFunctionCalls.push({
                      name:
                        chunk.item.tool_name ||
                        chunk.item.name ||
                        chunk.item.type ||
                        "unknown",
                      arguments: chunk.item.inputs || {},
                      status: "completed" as const,
                      id: chunk.item.id,
                      type: chunk.item.type,
                      result: chunk.item.results,
                    });
                  }
                } else if (
                  chunk.finish_reason === "error" ||
                  chunk.status === "failed"
                ) {
                  console.error("Error detected in stream");
                  isError = true;
                  throw new Error("Error detected in stream");
                } else if (chunk.type === "response.output_text.delta") {
                  currentContent += chunk.delta || "";
                } else if (
                  chunk.type === "response.completed" &&
                  chunk.response?.usage
                ) {
                  usageData = chunk.response.usage;
                } else if (chunk.output_text) {
                  currentContent += chunk.output_text;
                } else if (chunk.delta) {
                  if (typeof chunk.delta === "string")
                    currentContent += chunk.delta;
                  else if (
                    typeof chunk.delta === "object" &&
                    chunk.delta.text &&
                    !chunk.delta.content
                  )
                    currentContent += chunk.delta.text;
                }

                // Heuristic detection
                const hasImplicitToolCall =
                  (chunk.results &&
                    Array.isArray(chunk.results) &&
                    chunk.results.length > 0) ||
                  (chunk.outputs &&
                    Array.isArray(chunk.outputs) &&
                    chunk.outputs.length > 0) ||
                  chunk.retrieved_documents ||
                  chunk.retrieval_results ||
                  (chunk.data &&
                    typeof chunk.data === "object" &&
                    (chunk.data.results ||
                      chunk.data.retrieved_documents ||
                      chunk.data.retrieval_results));

                if (hasImplicitToolCall && currentFunctionCalls.length === 0) {
                  currentFunctionCalls.push({
                    name: "Retrieval",
                    arguments: { implicit: true, detected_heuristically: true },
                    status: "completed",
                    type: "retrieval_call",
                    result:
                      chunk.results ||
                      chunk.outputs ||
                      chunk.retrieved_documents ||
                      chunk.retrieval_results ||
                      chunk.data?.results ||
                      chunk.data?.retrieved_documents ||
                      [],
                  });
                }

                // Update living state
                if (
                  !controller.signal.aborted &&
                  thisStreamId === get().streamId
                ) {
                  set({
                    streamingMessage: {
                      role: "assistant",
                      content: currentContent,
                      functionCalls:
                        currentFunctionCalls.length > 0
                          ? [...currentFunctionCalls]
                          : undefined,
                      timestamp: new Date(),
                      isStreaming: true,
                    },
                  });
                }
              } catch (parseError) {
                console.warn("Failed to parse chunk:", line, parseError);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
        if (timeoutId) clearTimeout(timeoutId);
      }

      if (
        !hasReceivedData ||
        (!currentContent && currentFunctionCalls.length === 0)
      ) {
        throw new Error(
          "No response received from the server. Please try again.",
        );
      }

      // Post-processing
      if (currentFunctionCalls.length === 0 && currentContent) {
        if (
          /\(Source:|\[Source:|\bSource:|filename:|document:/i.test(
            currentContent,
          ) ||
          /based on.*(?:document|file|information|data)|according to.*(?:document|file)/i.test(
            currentContent,
          )
        ) {
          currentFunctionCalls.push({
            name: "Retrieval",
            arguments: { implicit: true, detected_from: "content_patterns" },
            status: "completed",
            type: "retrieval_call",
          });
        }
      }

      const finalMessage: Message = {
        role: "assistant",
        content: currentContent,
        functionCalls:
          currentFunctionCalls.length > 0 ? currentFunctionCalls : undefined,
        timestamp: new Date(),
        isStreaming: false,
        error: isError,
        usage: usageData,
      };

      if (!controller.signal.aborted && thisStreamId === get().streamId) {
        set({ streamingMessage: null, isLoading: false });
        get().callbacks.onComplete?.(finalMessage, newResponseId);
        return finalMessage;
      }

      return null;
    } catch (error) {
      if (timeoutId) clearTimeout(timeoutId);

      if (
        get().streamAbortController?.signal.aborted &&
        !(error as Error).message?.includes("timed out")
      ) {
        return null;
      }

      console.error("Chat stream error:", error);
      const errorMessage = (error as Error).message;
      let errorContent = errorMessage;
      if (errorMessage?.includes("timed out"))
        errorContent =
          "The request timed out. The server took too long to respond. Please try again.";
      else if (errorMessage?.includes("No response"))
        errorContent = "The server didn't return a response. Please try again.";
      else if (
        errorMessage?.includes("NetworkError") ||
        errorMessage?.includes("Failed to fetch")
      )
        errorContent =
          "Network error. Please check your connection and try again.";

      get().callbacks.onError?.(error as Error);

      const errorMessageObj: Message = {
        role: "assistant",
        content: errorContent,
        timestamp: new Date(),
        isStreaming: false,
        error: true,
      };

      if (
        !get().streamAbortController?.signal.aborted &&
        thisStreamId === get().streamId
      ) {
        get().callbacks.onComplete?.(errorMessageObj, null);
        set({ streamingMessage: null, isLoading: false });
      }

      return errorMessageObj;
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
      if (thisStreamId === get().streamId && get().isLoading) {
        set({ isLoading: false });
      }
    }
  },
}));
