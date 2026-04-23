// ABOUTME: Vite ImportMeta env typings for VITE_* variables read at runtime.
// ABOUTME: All custom vars must be declared here or tsc will reject import.meta.env.VITE_*.

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_R2_PUBLIC_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
