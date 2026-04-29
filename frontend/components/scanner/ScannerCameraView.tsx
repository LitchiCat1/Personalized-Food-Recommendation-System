import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { CameraView } from 'expo-camera';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography } from '@/constants/theme';

type Props = {
  cameraRef: React.RefObject<CameraView | null>;
  rs: (value: number) => number;
  topInset: number;
  onClose: () => void;
  onCapture: () => void;
};

const CORNER_SIZE = 24;
const CORNER_WIDTH = 3;

export default function ScannerCameraView({ cameraRef, rs, topInset, onClose, onCapture }: Props) {
  return (
    <View style={[styles.screen, { paddingTop: topInset }]}>
      <CameraView ref={cameraRef} style={styles.camera} facing="back">
        <View style={styles.cameraOverlay}>
          <View style={styles.cameraGuide}>
            <View style={[styles.corner, styles.cornerTL]} />
            <View style={[styles.corner, styles.cornerTR]} />
            <View style={[styles.corner, styles.cornerBL]} />
            <View style={[styles.corner, styles.cornerBR]} />
          </View>
          <Text style={[styles.cameraHint, { fontSize: rs(13) }]}>將食物對準框內</Text>
          <View style={styles.cameraActions}>
            <Pressable onPress={onClose} style={styles.cameraCancelBtn}>
              <Ionicons name="close" size={rs(24)} color={Palette.text.primary} />
            </Pressable>
            <Pressable onPress={onCapture} style={styles.shutterBtn}>
              <View style={styles.shutterInner} />
            </Pressable>
            <View style={{ width: rs(48) }} />
          </View>
        </View>
      </CameraView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.bg.primary },
  camera: { flex: 1 },
  cameraOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 60 },
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
  corner: { position: 'absolute', width: CORNER_SIZE, height: CORNER_SIZE },
  cornerTL: { top: 12, left: 12, borderTopWidth: CORNER_WIDTH, borderLeftWidth: CORNER_WIDTH, borderColor: Palette.accent.purple, borderTopLeftRadius: 4 },
  cornerTR: { top: 12, right: 12, borderTopWidth: CORNER_WIDTH, borderRightWidth: CORNER_WIDTH, borderColor: Palette.accent.purple, borderTopRightRadius: 4 },
  cornerBL: { bottom: 12, left: 12, borderBottomWidth: CORNER_WIDTH, borderLeftWidth: CORNER_WIDTH, borderColor: Palette.accent.cyan, borderBottomLeftRadius: 4 },
  cornerBR: { bottom: 12, right: 12, borderBottomWidth: CORNER_WIDTH, borderRightWidth: CORNER_WIDTH, borderColor: Palette.accent.cyan, borderBottomRightRadius: 4 },
});
