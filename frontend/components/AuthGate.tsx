import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import type { Session } from '@supabase/supabase-js';

import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import { isSupabaseAuthConfigured, supabase } from '@/lib/supabase';
import { useStore } from '@/store/useStore';


function applySession(session: Session | null) {
  const store = useStore.getState();
  if (!session?.user) {
    store.setAuthSession(null);
    return;
  }

  store.setAuthSession({
    userId: session.user.id,
    email: session.user.email,
    accessToken: session.access_token,
  });
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const authReady = useStore((state) => state.authReady);
  const isAuthenticated = useStore((state) => state.isAuthenticated);
  const setAuthReady = useStore((state) => state.setAuthReady);
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isSupabaseAuthConfigured || !supabase) {
      setAuthReady(true);
      return;
    }

    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      applySession(data.session);
      setAuthReady(true);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      applySession(session);
      setAuthReady(true);
    });

    return () => {
      active = false;
      listener.subscription.unsubscribe();
    };
  }, [setAuthReady]);

  const title = useMemo(() => mode === 'login' ? '登入 NutriLens' : '建立 NutriLens 帳號', [mode]);

  const submit = async () => {
    if (!supabase) return;
    setBusy(true);
    setMessage(null);
    try {
      const credentials = { email: email.trim(), password };
      const { data, error } = mode === 'login'
        ? await supabase.auth.signInWithPassword(credentials)
        : await supabase.auth.signUp(credentials);

      if (error) throw error;
      applySession(data.session);
      if (!data.session) {
        setMessage('請到信箱完成驗證後再登入。');
      }
    } catch (error: any) {
      setMessage(error?.message || '驗證失敗，請稍後再試。');
    } finally {
      setBusy(false);
    }
  };

  if (!isSupabaseAuthConfigured) {
    return <>{children}</>;
  }

  if (!authReady) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={Palette.accent.green} />
        <Text style={styles.mutedText}>正在確認登入狀態...</Text>
      </View>
    );
  }

  if (isAuthenticated) {
    return <>{children}</>;
  }

  return (
    <View style={styles.screen}>
      <View style={styles.card}>
        <Text style={styles.kicker}>Supabase Auth</Text>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.subtitle}>登入後，後端會用 Supabase access token 驗證你的 user_id。</Text>

        <TextInput
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          onChangeText={setEmail}
          placeholder="email@example.com"
          placeholderTextColor={Palette.text.tertiary}
          style={styles.input}
          value={email}
        />
        <TextInput
          autoCapitalize="none"
          onChangeText={setPassword}
          placeholder="至少 6 個字元的密碼"
          placeholderTextColor={Palette.text.tertiary}
          secureTextEntry
          style={styles.input}
          value={password}
        />

        {message ? <Text style={styles.message}>{message}</Text> : null}

        <Pressable disabled={busy} onPress={submit} style={[styles.primaryButton, busy && styles.disabledButton]}>
          {busy ? <ActivityIndicator color={Palette.bg.primary} /> : <Text style={styles.primaryText}>{mode === 'login' ? '登入' : '註冊'}</Text>}
        </Pressable>

        <Pressable onPress={() => setMode(mode === 'login' ? 'signup' : 'login')} style={styles.secondaryButton}>
          <Text style={styles.secondaryText}>{mode === 'login' ? '還沒有帳號？建立帳號' : '已有帳號？回到登入'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xl,
    backgroundColor: Palette.bg.primary,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.md,
    backgroundColor: Palette.bg.primary,
  },
  card: {
    width: '100%',
    maxWidth: 420,
    padding: Spacing.xl,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.card,
    ...Shadows.card,
  },
  kicker: {
    color: Palette.accent.green,
    fontSize: 12,
    fontWeight: Typography.label.fontWeight,
    letterSpacing: Typography.label.letterSpacing,
    marginBottom: Spacing.xs,
  },
  title: {
    color: Palette.text.primary,
    fontSize: 26,
    fontWeight: '800',
    marginBottom: Spacing.sm,
  },
  subtitle: {
    color: Palette.text.secondary,
    fontSize: 13,
    lineHeight: 20,
    marginBottom: Spacing.lg,
  },
  input: {
    color: Palette.text.primary,
    backgroundColor: Palette.bg.secondary,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
    marginBottom: Spacing.md,
  },
  message: {
    color: Palette.status.warning,
    fontSize: 12,
    marginBottom: Spacing.md,
  },
  mutedText: {
    color: Palette.text.secondary,
    fontSize: 13,
  },
  primaryButton: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 46,
    borderRadius: Radius.md,
    backgroundColor: Palette.accent.green,
  },
  disabledButton: {
    opacity: 0.7,
  },
  primaryText: {
    color: Palette.bg.primary,
    fontSize: 15,
    fontWeight: '800',
  },
  secondaryButton: {
    alignItems: 'center',
    marginTop: Spacing.md,
  },
  secondaryText: {
    color: Palette.accent.cyan,
    fontSize: 13,
    fontWeight: '700',
  },
});
