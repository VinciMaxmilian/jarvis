export const getApiBase = () => {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  // No build do Tauri, a origem é tauri.localhost ou tauri://localhost.
  // Como não há dev server rodando proxy em produção no desktop, precisamos 
  // bater direto no backend em 127.0.0.1:8000.
  // @ts-ignore
  if (window.__TAURI_INTERNALS__) {
    return 'http://127.0.0.1:8000';
  }
  return '';
};
