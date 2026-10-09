import Constants from 'expo-constants';
import { NativeModules, Platform } from 'react-native';

function extractHost(value?: string | null): string | null {
  if (!value) return null;
  const normalized = value.replace(/^https?:\/\//, '').replace(/^exp:\/\//, '').replace(/^exps:\/\//, '');
  const host = normalized.split('/')[0]?.split(':')[0];
  if (!host) return null;
  if (host.includes('expo.dev') || host.includes('exp.direct')) return null;
  return host;
}

function inferHostFromRuntime(): string | null {
  const sourceCodeUrl = NativeModules?.SourceCode?.scriptURL as string | undefined;
  const sourceCodeHost = extractHost(sourceCodeUrl);
  if (sourceCodeHost) return sourceCodeHost;

  const manifestDebuggerHost = (Constants as any)?.manifest?.debuggerHost as string | undefined;
  const manifest2DebuggerHost = (Constants as any)?.manifest2?.extra?.expoGo?.debuggerHost as string | undefined;
  const expoConfigHostUri = (Constants as any)?.expoConfig?.hostUri as string | undefined;

  return extractHost(manifestDebuggerHost) || extractHost(manifest2DebuggerHost) || extractHost(expoConfigHostUri);
}

export function normalizeApiBaseUrl(value: string): string {
  const normalized = value.trim().replace(/\/+$/, '');
  if (/^https?:\/\//i.test(normalized)) return normalized;
  const host = normalized.split('/')[0];
  const local = /^(localhost|127\.0\.0\.1|10\.0\.2\.2)(:\d+)?$/i.test(host)
    || /^192\.168\./.test(host)
    || /^10\./.test(host)
    || /^172\.(1[6-9]|2\d|3[0-1])\./.test(host);
  return `${local ? 'http' : 'https'}://${normalized}`;
}

function isLoopbackHost(host: string): boolean {
  return /^(localhost|127(\.\d+){3}|\[?::1\]?)$/i.test(host);
}

/**
 * 網頁版的 API 位址跟著網站走。
 *
 * - `same-origin`（`npm run build:local`）：網站由後端一起提供，API 就在同一個網址，
 *   不管是 localhost、區網 IP 還是 tunnel 的 https 網址都對。
 * - 設定的是 127.0.0.1 / localhost，但網站是用區網 IP 或 VPN 位址打開的：127.0.0.1
 *   在對方裝置上指的是對方自己，換成網站所在的主機。
 */
function resolveWebApiBaseUrl(explicitUrl: string | undefined): string | null {
  if (typeof window === 'undefined' || !window.location?.hostname) return null;
  if (explicitUrl === 'same-origin') return window.location.origin;
  const pageHost = window.location.hostname;
  if (isLoopbackHost(pageHost)) return null;
  const configured = new URL(explicitUrl ? normalizeApiBaseUrl(explicitUrl) : 'http://localhost:5000');
  if (!isLoopbackHost(configured.hostname)) return null;
  configured.hostname = pageHost;
  return configured.origin;
}

export function resolveApiBaseUrl(): string {
  const configuredUrl = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (Platform.OS === 'web') {
    const webUrl = resolveWebApiBaseUrl(configuredUrl);
    if (webUrl) return webUrl;
  }
  // same-origin 只對網頁版有意義；App 版照常從執行環境推導
  const explicitUrl = configuredUrl === 'same-origin' ? undefined : configuredUrl;
  if (explicitUrl) return normalizeApiBaseUrl(explicitUrl);

  const explicitHost = process.env.EXPO_PUBLIC_API_HOST?.trim();
  if (explicitHost) return `http://${explicitHost}:5000`;

  if (Platform.OS === 'web') return 'http://localhost:5000';

  const runtimeHost = inferHostFromRuntime();
  if (runtimeHost && runtimeHost !== 'localhost') {
    return `http://${runtimeHost}:5000`;
  }

  if (Platform.OS === 'android') {
    return 'http://10.0.2.2:5000';
  }

  return 'http://localhost:5000';
}
