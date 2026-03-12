"use client";

import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import GoogleLogo from "@/components/icons/google-logo";
import Logo from "@/components/icons/openrag-logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/auth-context";

function IbmLoginForm({ onSuccess }: { onSuccess: () => void }) {
  const { loginWithIbm } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await loginWithIbm(username, password);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 w-80">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          type="text"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          disabled={isSubmitting}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={isSubmitting}
        />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button
        type="submit"
        className="w-full"
        size="lg"
        disabled={isSubmitting}
      >
        {isSubmitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Signing in…
          </>
        ) : (
          "Sign in"
        )}
      </Button>
    </form>
  );
}

function LoginPageContent() {
  const { isLoading, isAuthenticated, isNoAuthMode, isIbmAuthMode, login } =
    useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const redirect = searchParams.get("redirect") || "/chat";

  useEffect(() => {
    if (!isLoading && (isAuthenticated || isNoAuthMode)) {
      router.push(redirect);
    }
  }, [isLoading, isAuthenticated, isNoAuthMode, router, redirect]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  if (isAuthenticated || isNoAuthMode) {
    return null; // Will redirect in useEffect
  }

  return (
    <div className="min-h-dvh relative flex gap-4 flex-col items-center justify-center bg-card rounded-lg m-4">
      <div className="flex flex-col items-center justify-center gap-4 z-10 ">
        <Logo className="fill-primary" width={50} height={40} />
        <div className="flex flex-col items-center justify-center gap-16">
          <h1 className="text-2xl font-medium font-chivo">
            Welcome to OpenRAG
          </h1>
          {isIbmAuthMode ? (
            <IbmLoginForm onSuccess={() => router.push(redirect)} />
          ) : (
            <Button onClick={login} className="w-80 gap-1.5" size="lg">
              <GoogleLogo className="h-4 w-4" />
              Continue with Google
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-background">
          <div className="flex flex-col items-center gap-4">
            <Loader2 className="h-8 w-8 animate-spin" />
            <p className="text-muted-foreground">Loading...</p>
          </div>
        </div>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}
