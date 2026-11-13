import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import Constants from 'expo-constants';
import { Link, usePathname } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';
import { useStore } from '@/store/useStore';

/**
 * 版本號跟著 app.json 的 expo.version 走，不要寫死。
 *
 * 這裡原本掛著 'v0.0.8f'，而程式早就到 v0.0.9 了（app.json、package.json、
 * 後端 /health 的 app_version 全是）。一個對不上的版本號會讓「線上跑的是哪
 * 一版」得靠猜。
 *
 * 注意：本機 `expo start` 時這個值可能是舊的——實測回過 0.0.4，五個版本以前
 * 的數字，而且清 .expo/cache 與 node_modules/.cache 都沒用（卡在系統 temp 的
 * metro-cache，要一併刪掉）。`expo export` 產出的正式 bundle 沒有這個問題，
 * 裡面的 config 是當次解析出來的。所以標籤在部署後是準的，本機看到怪數字先
 * 想到快取。
 */
const APP_VERSION = Constants.expoConfig?.version || '';

const NAV_ITEMS = [
  { href: '/', label: '首頁', icon: 'home-outline' },
  { href: '/scanner', label: '辨識', icon: 'scan-outline' },
  { href: '/recommend', label: '店家', icon: 'location-outline' },
  { href: '/history', label: '趨勢', icon: 'bar-chart-outline' },
  { href: '/profile', label: '我的', icon: 'person-outline' },
] as const;

export default function DesktopSidebar() {
  const pathname = usePathname();
  const user = useStore((state) => state.user);

  return (
    <View style={styles.sidebar}>
      <View style={styles.brandBlock}>
        <Text style={styles.brand}>NutriLens</Text>
        <Text style={styles.tagline}>AI food safety radar</Text>
        {APP_VERSION ? (
          <View style={styles.versionPill}>
            <Text style={styles.versionText}>v{APP_VERSION}</Text>
          </View>
        ) : null}
      </View>

      <View style={styles.navigation} accessibilityRole="tablist">
        {NAV_ITEMS.map((item, index) => {
          const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
          return (
            <Link key={item.href} href={item.href} asChild>
              <Pressable
                accessibilityRole="tab"
                accessibilityLabel={`前往${item.label}`}
                aria-selected={active}
                style={({ pressed }) => [styles.navItem, active && styles.navItemActive, pressed && styles.navItemPressed]}
              >
                <Text style={[styles.navIndex, active && styles.navActiveText]}>{String(index + 1).padStart(2, '0')}</Text>
                <Ionicons name={item.icon} size={19} color={active ? Palette.accent.green : '#A8BAB1'} />
                <Text style={[styles.navLabel, active && styles.navActiveText]}>{item.label}</Text>
              </Pressable>
            </Link>
          );
        })}
      </View>

      <View style={styles.accountBlock}>
        <Text style={styles.accountName} numberOfLines={1}>
          {user.name.trim() || (user.email || '').split('@')[0] || '尚未設定名稱'}
        </Text>
        {/* 先前這行寫死「健康條件已同步」——同步失敗時也照樣這樣寫。
            真正的同步狀態在「我的」頁上，這裡只說這個檔案填了沒有。 */}
        <Text style={styles.accountStatus}>
          {user.profileComplete ? '健康檔案已設定' : '尚未完成基本資料'}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  sidebar: {
    width: 220,
    minHeight: '100%',
    backgroundColor: '#10241E',
    padding: Spacing.xl,
    gap: Spacing.xl,
  },
  brandBlock: { gap: Spacing.xs },
  brand: { ...Typography.h1, color: Palette.text.inverse },
  tagline: { ...Typography.caption, color: '#A8BAB1' },
  versionPill: {
    alignSelf: 'flex-start',
    marginTop: Spacing.sm,
    minHeight: 32,
    minWidth: 96,
    borderRadius: Radius.full,
    backgroundColor: '#17372D',
    justifyContent: 'center',
    paddingHorizontal: Spacing.md,
  },
  versionText: { ...Typography.small, color: '#65D1A3', fontWeight: '700' },
  navigation: { gap: Spacing.sm, flex: 1 },
  navItem: {
    minHeight: 48,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  navItemActive: { backgroundColor: Palette.accent.greenDim },
  navItemPressed: { opacity: 0.78 },
  navIndex: { ...Typography.small, color: '#A8BAB1', width: 24 },
  navLabel: { ...Typography.bodyBold, color: '#D7E2DD' },
  navActiveText: { color: Palette.accent.green },
  accountBlock: {
    backgroundColor: '#17372D',
    borderRadius: Radius.lg,
    padding: Spacing.md,
    gap: 3,
  },
  accountName: { ...Typography.bodyBold, color: Palette.text.inverse },
  accountStatus: { ...Typography.small, color: '#A8BAB1' },
});
