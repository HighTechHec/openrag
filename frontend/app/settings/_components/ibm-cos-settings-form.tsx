"use client";

import { useFormContext, Controller } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Loader2, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface IBMCOSFormData {
    auth_mode: "iam" | "hmac";
    endpoint: string;
    // IAM
    api_key: string;
    service_instance_id: string;
    // HMAC
    hmac_access_key: string;
    hmac_secret_key: string;
}

interface IBMCOSSettingsFormProps {
    /** Available buckets after a successful test — null means not yet tested */
    buckets: string[] | null;
    selectedBuckets: string[];
    onSelectedBucketsChange: (buckets: string[]) => void;
    isFetchingBuckets: boolean;
    bucketsError: string | null;
    onTestConnection: () => void;
    apiKeySet?: boolean;
    hmacAccessKeySet?: boolean;
    hmacSecretKeySet?: boolean;
    formError?: string | null;
}

export function IBMCOSSettingsForm({
    buckets,
    selectedBuckets,
    onSelectedBucketsChange,
    isFetchingBuckets,
    bucketsError,
    onTestConnection,
    apiKeySet,
    hmacAccessKeySet,
    hmacSecretKeySet,
    formError,
}: IBMCOSSettingsFormProps) {
    const {
        register,
        control,
        formState: { errors },
    } = useFormContext<IBMCOSFormData>();

    const toggleBucket = (name: string, checked: boolean) => {
        if (checked) {
            onSelectedBucketsChange([...selectedBuckets, name]);
        } else {
            onSelectedBucketsChange(selectedBuckets.filter((b) => b !== name));
        }
    };

    const toggleAll = (checked: boolean) => {
        onSelectedBucketsChange(checked ? (buckets ?? []) : []);
    };

    return (
        <div className="space-y-5">
            {/* Auth mode selector using Tabs */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Authentication Method</Label>
                <Controller
                    control={control}
                    name="auth_mode"
                    render={({ field }) => (
                        <Tabs value={field.value} onValueChange={field.onChange}>
                            <TabsList className="w-full">
                                <TabsTrigger value="iam">
                                    <span className="font-semibold text-sm">IAM</span>
                                    <span className="text-xs text-muted-foreground font-normal">
                                        API Key + Service Instance ID
                                    </span>
                                </TabsTrigger>
                                <TabsTrigger value="hmac">
                                    <span className="font-semibold text-sm">HMAC</span>
                                    <span className="text-xs text-muted-foreground font-normal">
                                        Access Key + Secret Key
                                    </span>
                                </TabsTrigger>
                            </TabsList>

                            {/* IAM fields */}
                            <TabsContent value="iam">
                                <div className="space-y-4">
                                    <div className="space-y-1">
                                        <LabelWrapper
                                            label="API Key"
                                            helperText="IBM Cloud IAM API key"
                                            id="ibm-cos-api-key"
                                            required
                                        >
                                            <Input
                                                {...register("api_key")}
                                                id="ibm-cos-api-key"
                                                type="password"
                                                placeholder={
                                                    apiKeySet
                                                        ? "•••••••• (loaded from env)"
                                                        : "Enter API key"
                                                }
                                                autoComplete="off"
                                            />
                                        </LabelWrapper>
                                    </div>
                                    <div className="space-y-1">
                                        <LabelWrapper
                                            label="Service Instance ID (CRN)"
                                            helperText="CRN of your COS service instance"
                                            id="ibm-cos-svc-id"
                                            required
                                        >
                                            <Input
                                                {...register("service_instance_id")}
                                                id="ibm-cos-svc-id"
                                                placeholder="crn:v1:bluemix:..."
                                            />
                                        </LabelWrapper>
                                    </div>
                                </div>
                            </TabsContent>

                            {/* HMAC fields */}
                            <TabsContent value="hmac">
                                <div className="space-y-4">
                                    <div className="space-y-1">
                                        <LabelWrapper
                                            label="HMAC Access Key ID"
                                            id="ibm-cos-hmac-key"
                                            required
                                        >
                                            <Input
                                                {...register("hmac_access_key")}
                                                id="ibm-cos-hmac-key"
                                                type="password"
                                                placeholder={
                                                    hmacAccessKeySet
                                                        ? "•••••••• (loaded from env)"
                                                        : "Enter access key ID"
                                                }
                                                autoComplete="off"
                                            />
                                        </LabelWrapper>
                                    </div>
                                    <div className="space-y-1">
                                        <LabelWrapper
                                            label="HMAC Secret Access Key"
                                            id="ibm-cos-hmac-secret"
                                            required
                                        >
                                            <Input
                                                {...register("hmac_secret_key")}
                                                id="ibm-cos-hmac-secret"
                                                type="password"
                                                placeholder={
                                                    hmacSecretKeySet
                                                        ? "•••••••• (loaded from env)"
                                                        : "Enter secret access key"
                                                }
                                                autoComplete="off"
                                            />
                                        </LabelWrapper>
                                    </div>
                                </div>
                            </TabsContent>
                        </Tabs>
                    )}
                />
            </div>

            {/* Endpoint — shared by both auth modes */}
            <div className="space-y-1">
                <LabelWrapper
                    label="Service Endpoint"
                    helperText="e.g. https://s3.us-south.cloud-object-storage.appdomain.cloud"
                    id="ibm-cos-endpoint"
                    required
                >
                    <Input
                        {...register("endpoint", { required: "Endpoint is required" })}
                        id="ibm-cos-endpoint"
                        placeholder="https://s3.us-south.cloud-object-storage.appdomain.cloud"
                        className={errors.endpoint ? "!border-destructive" : ""}
                    />
                </LabelWrapper>
                {errors.endpoint && (
                    <p className="text-sm text-destructive">{errors.endpoint.message}</p>
                )}
            </div>

            {/* Test connection */}
            <Button
                type="button"
                variant="outline"
                onClick={onTestConnection}
                disabled={isFetchingBuckets}
                className="w-full"
            >
                {isFetchingBuckets ? (
                    <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Connecting…
                    </>
                ) : buckets !== null ? (
                    <>
                        <RefreshCcw className="h-4 w-4 mr-2" />
                        Refresh Buckets
                    </>
                ) : (
                    "Test Connection & List Buckets"
                )}
            </Button>

            {bucketsError && (
                <p className="text-sm text-destructive rounded-lg border border-destructive/50 p-3">
                    {bucketsError}
                </p>
            )}

            {formError && (
                <p className="text-sm text-destructive rounded-lg border border-destructive/50 p-3">
                    {formError}
                </p>
            )}

            {/* Bucket selector — native checkboxes styled with Tailwind */}
            {buckets !== null && (
                <div className="space-y-2">
                    <div className="flex items-center justify-between">
                        <Label className="text-sm font-medium">
                            Select Buckets to Ingest
                            <span className="ml-1 text-muted-foreground font-normal">
                                (leave all unchecked to ingest everything)
                            </span>
                        </Label>
                        {buckets.length > 1 && (
                            <button
                                type="button"
                                className="text-xs text-primary underline-offset-2 hover:underline"
                                onClick={() =>
                                    toggleAll(selectedBuckets.length !== buckets.length)
                                }
                            >
                                {selectedBuckets.length === buckets.length
                                    ? "Deselect all"
                                    : "Select all"}
                            </button>
                        )}
                    </div>

                    {buckets.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                            No buckets found for this account.
                        </p>
                    ) : (
                        <div className="max-h-48 overflow-y-auto rounded-lg border p-3 space-y-2">
                            {buckets.map((bucket) => (
                                <label
                                    key={bucket}
                                    htmlFor={`bucket-${bucket}`}
                                    className="flex items-center gap-2.5 cursor-pointer select-none"
                                >
                                    <input
                                        id={`bucket-${bucket}`}
                                        type="checkbox"
                                        className="h-4 w-4 rounded border-border accent-primary"
                                        checked={selectedBuckets.includes(bucket)}
                                        onChange={(e) =>
                                            toggleBucket(bucket, e.target.checked)
                                        }
                                    />
                                    <span className="text-sm">{bucket}</span>
                                </label>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
