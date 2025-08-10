/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_ADSENSE_CLIENT?: string; // e.g. ca-pub-XXXXXXXXXXXXXXXX
  readonly VITE_ADSENSE_SLOT_GENERATE?: string; // numeric slot id for generation modal
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
