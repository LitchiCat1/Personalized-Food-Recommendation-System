import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { Link, usePathname } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';
import { useStore } from '@/store/useStore';

const NAV_ITEMS = [
  { href: '/', label: '首頁', icon: 'home-outline' },
  { href: '/scanner', label: '辨識', icon: 'scan-outline' },
  { href: '/recommend', label: '推薦', icon: 'sparkles-outline' },
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
        <View style={styles.versionPill}>
          <Text style={styles.versionText}>v0.0.7</Text>
        </View>
      </View>

      <View style={styles.navigation} accessibilityRole="tablist">
        {NAV_ITEMS.map((item, index) => {
          const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
          return (
            <Link key={item.href} href={item.href} asChild>
              <Pressable
                accessibilityRole="tab"
                accessibilityLabel={`前往${item.label}`}
                accessibilityState={{ selected: active }}
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
        <Text style={styles.accountName} numberOfLines={1}>{user.name}</Text>
        <Text style={styles.accountStatus}>健康條件已同步</Text>
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
