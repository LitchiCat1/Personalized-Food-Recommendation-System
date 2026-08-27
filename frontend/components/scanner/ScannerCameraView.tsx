import React from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { CameraView } from 'expo-camera';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography } from '@/constants/theme';

type Props = {
  cameraRef: React.RefObject<CameraView | null>;
  rs: (value: number) => number;
  topInset: number;
  isReady: boolean;
  isCapturing: boolean;
  onClose: () => void;
  onCapture: () => void;
  onReady: () => void;
  onError: (message: string) => void;
};

const CORNER_SIZE = 24;
const CORNER_WIDTH = 3;

export default function ScannerCameraView({
  cameraRef,
  rs,
  topInset,
  isReady,
  isCapturing,
  onClose,
  onCapture,
  onReady,
  onError,
}: Props) {
  return (
    <View style={[styles.screen, { paddingTop: topInset }]}>
      <CameraView
        ref={cameraRef}
        style={styles.camera}
        facing="back"
        mode="picture"
        onCameraReady={onReady}
        onMountError={(error) => onError(error.message)}
      />
      <View style={styles.cameraOverlay}>
        {!isReady ? (
          <View style={styles.loadingCamera}>
            <ActivityIndicator size="large" color="#fff" />
            <Text style={styles.loadingText}>正在啟動相機</Text>
          </View>
        ) : null}
        <View style={styles.cameraGuide}>
          <View style={[styles.corner, styles.cornerTL]} />
          <View style={[styles.corner, styles.cornerTR]} />
          <View style={[styles.corner, styles.cornerBL]} />
          <View style={[styles.corner, styles.cornerBR]} />
        </View>
        <Text style={[styles.cameraHint, { fontSize: rs(13) }]}>將食物對準框內</Text>
        <View style={styles.cameraActions}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="關閉相機"
            disabled={isCapturing}
            onPress={onClose}
            style={[styles.cameraCancelBtn, isCapturing && styles.disabledAction]}
          >
            <Ionicons name="close" size={rs(24)} color={Palette.text.primary} />
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={isCapturing ? '正在拍攝' : '拍攝食物照片'}
            disabled={!isReady || isCapturing}
            onPress={onCapture}
            style={[styles.shutterBtn, (!isReady || isCapturing) && styles.disabledAction]}
          >
            {isCapturing ? <ActivityIndicator color="#fff" /> : <View style={styles.shutterInner} />}
          </Pressable>
          <View style={{ width: rs(48) }} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.bg.primary },
  camera: { flex: 1 },
  cameraOverlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.3)', justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 60 },
  loadingCamera: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center', gap: 12, backgroundColor: 'rgba(0,0,0,0.45)' },
  loadingText: { ...Typography.bodyBold, color: '#fff' },
  cameraGuide: { width: 260, height: 260, position: 'absolute', top: '30%' },
  cameraHint: { ...Typography.body, color: '#fff', marginBottom: 40 },
  cameraActions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-around', width: '80%' },
  cameraCancelBtn: {
    width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterBtn: {
    width: 72, height: 72, borderRadius: 36, borderWidth: 4, borderColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterInner: { width: 58, height: 58, borderRadius: 29, backgroundColor: '#fff' },
  disabledAction: { opacity: 0.48 },
  corner: { position: 'absolute', width: CORNER_SIZE, height: CORNER_SIZE },
  cornerTL: { top: 12, left: 12, borderTopWidth: CORNER_WIDTH, borderLeftWidth: CORNER_WIDTH, borderColor: Palette.accent.purple, borderTopLeftRadius: 4 },
  cornerTR: { top: 12, right: 12, borderTopWidth: CORNER_WIDTH, borderRightWidth: CORNER_WIDTH, borderColor: Palette.accent.purple, borderTopRightRadius: 4 },
  cornerBL: { bottom: 12, left: 12, borderBottomWidth: CORNER_WIDTH, borderLeftWidth: CORNER_WIDTH, borderColor: Palette.accent.cyan, borderBottomLeftRadius: 4 },
  cornerBR: { bottom: 12, right: 12, borderBottomWidth: CORNER_WIDTH, borderRightWidth: CORNER_WIDTH, borderColor: Palette.accent.cyan, borderBottomRightRadius: 4 },
});
