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

export function resolveApiBaseUrl(): string {
  const explicitUrl = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (explicitUrl) return explicitUrl;

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
