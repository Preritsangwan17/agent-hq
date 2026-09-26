/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" → in-browser simulator answers /api and /api/stream (src/lib/mock). */
  readonly VITE_MOCK?: string;
  /** Optional absolute API origin; default same-origin (Vite proxy in dev, FastAPI in prod). */
  readonly VITE_API_BASE?: string;
  /** Dev-server proxy target for /api (read in vite.config.ts). */
  readonly VITE_API_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
