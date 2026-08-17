import 'react-native-url-polyfill/auto';

import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient } from '@supabase/supabase-js';
import { Platform } from 'react-native';


const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL?.trim();
const supabasePublishableKey = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim()
  || process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY?.trim();
const supabaseAuthFlag = process.env.EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED?.trim().toLowerCase();

function isValidHttpUrl(value?: string) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch {
    return false;
  }
}

export const isSupabaseAuthConfigured = Boolean(isValidHttpUrl(supabaseUrl) && supabasePublishableKey);
export const isSupabaseAuthRequired = supabaseAuthFlag === 'true';
export const supabaseConfigurationError = isSupabaseAuthRequired && !isSupabaseAuthConfigured
  ? '部署缺少有效的 EXPO_PUBLIC_SUPABASE_URL 或 EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY，已停止載入示範帳號。'
  : null;

const supabaseStorage = Platform.OS === 'web'
  ? {
      getItem: (key: string) => (typeof window === 'undefined' ? null : window.localStorage.getItem(key)),
      setItem: (key: string, value: string) => {
        if (typeof window !== 'undefined') window.localStorage.setItem(key, value);
      },
      removeItem: (key: string) => {
        if (typeof window !== 'undefined') window.localStorage.removeItem(key);
      },
    }
  : AsyncStorage;

export const supabase = isSupabaseAuthConfigured
  ? createClient(supabaseUrl!, supabasePublishableKey!, {
      auth: {
        storage: supabaseStorage,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: false,
      },
    })
  : null;

export async function getSupabaseAccessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token || null;
}
