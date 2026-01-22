// URL path settings
export const api_url: string | null = import.meta.env.VITE_API_URL || null
export const ws_url: string | null = import.meta.env.VITE_WS_URL || null

// Title settings
export const documentTitlePrefix: string = import.meta.env.VITE_DOCUMENT_TITLE_PREFIX || ''
export const documentTitleSuffix: string = import.meta.env.VITE_DOCUMENT_TITLE_SUFFIX || 'UNKNOWN'
export const documentTitleSeparator: string = import.meta.env.VITE_DOCUMENT_TITLE_SEPARATOR || ' - '
