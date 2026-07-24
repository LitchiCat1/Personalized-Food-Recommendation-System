import React, { useState, useEffect, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Platform,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import PrimaryButton from '@/components/ui/primary-button';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import {
  searchRestaurants,
  scrapeAndEnrichRestaurant,
  addDietaryRecord,
  fetchRecords,
  type HealthyFoodRestaurant,
  type HealthyFoodRecommendation,
} from '@/lib/api';

export default function MenuQueryScreen() {
  const { apiBaseUrl, accessToken, replaceDashboardFromRecords, user } = useStore();

  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [restaurants, setRestaurants] = useState<HealthyFoodRestaurant[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Modal 控制
  const [recordModalVisible, setRecordModalVisible] = useState(false);
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [selectedMealType, setSelectedMealType] = useState<'早餐' | '午餐' | '晚餐' | '點心'>('午餐');
  const [recording, setRecording] = useState(false);

  // AI 新增/更新菜單 Modal 控制
  const [aiModalVisible, setAiModalVisible] = useState(false);
  const [aiRestaurantName, setAiRestaurantName] = useState('');
  const [aiAddress, setAiAddress] = useState('');
  const [aiMenuUrl, setAiMenuUrl] = useState('');
  const [aiMenuText, setAiMenuText] = useState('');
  const [aiLoading, setAiLoading] = useState(false);

  // 初始載入：空白搜尋或預載入
  useEffect(() => {
    handleSearch('');
  }, []);

  const handleSearch = async (query: string) => {
    setLoading(true);
    try {
      const data = await searchRestaurants(apiBaseUrl, query, { accessToken });
      setRestaurants(data.restaurants || []);
      // 預設展開第一家
      if (data.restaurants && data.restaurants.length > 0) {
        setExpandedId(data.restaurants[0].restaurant_id);
      } else {
        setExpandedId(null);
      }
    } catch (err: any) {
      console.warn('搜尋餐廳失敗:', err);
    } finally {
      setLoading(false);
    }
  };

  // 打開一鍵紀錄 Modal
  const openRecordModal = (item: any, restaurant: HealthyFoodRestaurant) => {
    setSelectedItem({
      ...item,
      restaurant_name: restaurant.name,
      restaurant_id: restaurant.restaurant_id,
    });
    // 根據當前時間推算預設餐點時段
    const hour = new Date().getHours();
    if (hour < 10) setSelectedMealType('早餐');
    else if (hour < 14) setSelectedMealType('午餐');
    else if (hour < 17) setSelectedMealType('點心');
    else setSelectedMealType('晚餐');
    
    setRecordModalVisible(true);
  };

  // 執行記錄餐點到今日飲食
  const handleAddRecord = async () => {
    if (!selectedItem) return;
    setRecording(true);
    try {
      const foodPayload = {
        name: `${selectedItem.restaurant_name} - ${selectedItem.item_name || selectedItem.name}`,
        calories: Number(selectedItem.calories || 0),
        protein: Number(selectedItem.protein || 0),
        carbs: Number(selectedItem.carbs || 0),
        fat: Number(selectedItem.fat || 0),
        sodium: Number(selectedItem.sodium || 0),
        fiber: Number(selectedItem.fiber || 0),
        source: 'manual',
      };

      const payload = {
        user_id: user.userId,
        meal_type: selectedMealType,
        foods: [foodPayload],
        total_calories: foodPayload.calories,
        total_protein: foodPayload.protein,
        total_carbs: foodPayload.carbs,
        total_fat: foodPayload.fat,
        total_sodium: foodPayload.sodium,
        total_fiber: foodPayload.fiber,
        source: 'manual',
      };

      await addDietaryRecord(apiBaseUrl, payload, { accessToken });
      
      // 同步更新 Zustand store 的今日進度
      const now = new Date();
      const yyyy = now.getFullYear();
      const mm = String(now.getMonth() + 1).padStart(2, '0');
      const dd = String(now.getDate()).padStart(2, '0');
      const dateStr = `${yyyy}-${mm}-${dd}`;
      const recordsData = await fetchRecords(apiBaseUrl, user.userId, dateStr, { accessToken });
      replaceDashboardFromRecords(recordsData.records || []);

      Alert.alert('記錄成功', `已成功將「${foodPayload.name}」加入今日${selectedMealType}！`);
      setRecordModalVisible(false);
    } catch (err: any) {
      Alert.alert('記錄失敗', err.message || '無法將餐點寫入紀錄');
    } finally {
      setRecording(false);
    }
  };

  // 打開 AI 生成/更新視窗
  const openAiModal = (existingRestaurant?: HealthyFoodRestaurant) => {
    if (existingRestaurant) {
      setAiRestaurantName(existingRestaurant.name);
      setAiAddress(existingRestaurant.address || '');
      setAiMenuUrl('');
      setAiMenuText('');
    } else {
      setAiRestaurantName(searchQuery);
      setAiAddress('');
      setAiMenuUrl('');
      setAiMenuText('');
    }
    setAiModalVisible(true);
  };

  // 提交 AI 分析與寫入
  const handleAiSubmit = async () => {
    if (!aiRestaurantName.trim()) {
      Alert.alert('請輸入餐廳名稱');
      return;
    }
    setAiLoading(true);
    try {
      await scrapeAndEnrichRestaurant(
        apiBaseUrl,
        {
          restaurant_name: aiRestaurantName,
          address: aiAddress || '台灣',
          menu_url: aiMenuUrl,
          menu_text: aiMenuText,
        },
        { accessToken }
      );
      Alert.alert('更新成功', 'AI 已經成功分析菜單並載入資料庫！');
      setAiModalVisible(false);
      // 重新搜尋，展現新菜單
      handleSearch(aiRestaurantName);
    } catch (err: any) {
      Alert.alert('生成失敗', err.message || 'Gemini AI 菜單生成服務目前忙碌中，請稍後再試。');
    } finally {
      setAiLoading(false);
    }
  };

  // 檢查餐點是否與使用者的疾病或過敏原衝突，提供個人化警示
  const evaluateItemSafety = (item: any) => {
    const alerts: string[] = [];
    
    // 1. 鈉含量警告：若有高血壓且鈉大於 400mg
    const hasHypertension = user.healthConditions.some(
      (c) => c.includes('血壓') || c.toLowerCase().includes('hypertension')
    );
    if (hasHypertension && item.sodium > 400) {
      alerts.push(`高鈉警示 (${item.sodium}mg)`);
    }

    // 2. 碳水/GI警告：若有糖尿病且碳水大於 60g 或 GI 為 high
    const hasDiabetes = user.healthConditions.some(
      (c) => c.includes('糖尿') || c.toLowerCase().includes('diabetes')
    );
    if (hasDiabetes && (item.carbs > 60 || item.gi === 'high')) {
      alerts.push('高碳水/高GI');
    }

    // 3. 過敏原警告
    const itemAllergens = item.allergens || [];
    const matchedAllergens = itemAllergens.filter((allergen: string) =>
      user.allergens.some(
        (ua) => ua.toLowerCase().includes(allergen.toLowerCase()) || allergen.toLowerCase().includes(ua.toLowerCase())
      )
    );
    if (matchedAllergens.length > 0) {
      alerts.push(`含過敏原: ${matchedAllergens.join('、')}`);
    }

    return {
      isSafe: alerts.length === 0,
      reasons: alerts,
    };
  };

  return (
    <AppContainer>
      <ScreenHeader
        title="找餐廳，查菜單"
        subtitle="搜尋資料庫中的現成菜單；或者提供菜單網址/文字，讓 AI 為您即時結構化其營養與安全成分！"
      />

      {/* 搜尋欄 */}
      <View style={styles.searchContainer}>
        <View style={styles.searchInputWrapper}>
          <Ionicons name="search" size={20} color={Palette.text.tertiary} style={styles.searchIcon} />
          <TextInput
            placeholder="請輸入餐廳名稱或標籤..."
            placeholderTextColor={Palette.text.muted}
            value={searchQuery}
            onChangeText={setSearchQuery}
            onSubmitEditing={() => handleSearch(searchQuery)}
            style={styles.searchInput}
          />
          {searchQuery ? (
            <TouchableOpacity onPress={() => setSearchQuery('')}>
              <Ionicons name="close-circle" size={18} color={Palette.text.tertiary} />
            </TouchableOpacity>
          ) : null}
        </View>
        <TouchableOpacity style={styles.searchButton} onPress={() => handleSearch(searchQuery)}>
          <Text style={styles.searchButtonText}>搜尋</Text>
        </TouchableOpacity>
      </View>

      {/* 快速新增全新餐廳按鈕 */}
      <TouchableOpacity
        style={styles.quickAddCard}
        onPress={() => openAiModal()}
      >
        <Ionicons name="cloud-upload-outline" size={20} color={Palette.accent.green} />
        <Text style={styles.quickAddText}>查不到店？點此提供網址或貼上菜單文字，讓 AI 為你快速新增！</Text>
        <Ionicons name="chevron-forward" size={16} color={Palette.text.muted} />
      </TouchableOpacity>

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {loading ? (
          <View style={styles.centerContainer}>
            <ActivityIndicator size="large" color={Palette.accent.green} />
            <Text style={styles.loadingText}>正為您檢索菜單資料庫...</Text>
          </View>
        ) : restaurants.length === 0 ? (
          /* 空狀態：引導 AI 生成 */
          <View style={styles.emptyContainer}>
            <View style={styles.emptyIconCircle}>
              <Ionicons name="restaurant-outline" size={40} color={Palette.text.muted} />
            </View>
            <Text style={styles.emptyTitle}>未找到類似的餐廳</Text>
            <Text style={styles.emptySubtitle}>
              資料庫目前沒有「{searchQuery || '此餐廳'}」的菜單。點擊下方按鈕，請 AI 廚師為您即時建立這家店的招牌菜餚！
            </Text>
            <TouchableOpacity style={styles.aiGenerateButton} onPress={() => openAiModal()}>
              <Ionicons name="sparkles" size={18} color={Palette.text.inverse} style={{ marginRight: 6 }} />
              <Text style={styles.aiGenerateButtonText}>由 AI 即時產生菜單與營養估算</Text>
            </TouchableOpacity>
          </View>
        ) : (
          /* 餐廳與菜單展開列表 */
          <View style={styles.restaurantList}>
            {restaurants.map((restaurant) => {
              const isExpanded = expandedId === restaurant.restaurant_id;
              return (
                <View key={restaurant.restaurant_id} style={[styles.restaurantCard, isExpanded && styles.restaurantCardExpanded]}>
                  {/* 餐廳 Header 行 */}
                  <TouchableOpacity
                    style={styles.restaurantHeader}
                    onPress={() => setExpandedId(isExpanded ? null : restaurant.restaurant_id)}
                    activeOpacity={0.8}
                  >
                    <View style={styles.restaurantHeaderInfo}>
                      <Text style={styles.restaurantName}>{restaurant.name}</Text>
                      {restaurant.address ? (
                        <Text style={styles.restaurantAddress} numberOfLines={1}>
                          📍 {restaurant.address}
                        </Text>
                      ) : null}
                      <View style={styles.tagRow}>
                        {restaurant.tags?.map((tag, idx) => (
                          <View key={idx} style={styles.tagPill}>
                            <Text style={styles.tagPillText}>{tag}</Text>
                          </View>
                        ))}
                      </View>
                    </View>
                    <Ionicons
                      name={isExpanded ? 'chevron-up' : 'chevron-down'}
                      size={20}
                      color={Palette.text.secondary}
                    />
                  </TouchableOpacity>

                  {/* 菜單展開內容 */}
                  {isExpanded && (
                    <View style={styles.menuContainer}>
                      {/* 操作區：更新菜單 */}
                      <View style={styles.menuActionBar}>
                        <Text style={styles.menuTitle}>經典招牌菜色 ({restaurant.items?.length || 0})</Text>
                        <TouchableOpacity
                          style={styles.updateMenuBtn}
                          onPress={() => openAiModal(restaurant)}
                        >
                          <Ionicons name="sync-outline" size={14} color={Palette.accent.green} style={{ marginRight: 4 }} />
                          <Text style={styles.updateMenuBtnText}>更新菜單資料</Text>
                        </TouchableOpacity>
                      </View>

                      {/* 菜單項目列表 */}
                      {restaurant.items && restaurant.items.length > 0 ? (
                        restaurant.items.map((item: any, idx: number) => {
                          const safety = evaluateItemSafety(item);
                          return (
                            <View key={idx} style={styles.menuItemCard}>
                              <View style={styles.menuItemTop}>
                                <View style={styles.menuItemTitleBlock}>
                                  <Text style={styles.menuItemName}>{item.name || item.item_name}</Text>
                                  {item.price ? (
                                    <Text style={styles.menuItemPrice}>${item.price}</Text>
                                  ) : null}
                                </View>
                                <TouchableOpacity
                                  style={styles.recordButton}
                                  onPress={() => openRecordModal(item, restaurant)}
                                >
                                  <Ionicons name="add" size={16} color={Palette.text.inverse} style={{ marginRight: 2 }} />
                                  <Text style={styles.recordButtonText}>記錄</Text>
                                </TouchableOpacity>
                              </View>

                              {/* 營養素條狀概要 */}
                              <View style={styles.nutritionRow}>
                                <View style={styles.nutrientBadge}>
                                  <Text style={styles.nutrientValue}>{item.calories} <Text style={styles.nutrientUnit}>kcal</Text></Text>
                                  <Text style={styles.nutrientLabel}>熱量</Text>
                                </View>
                                <View style={styles.nutrientBadge}>
                                  <Text style={styles.nutrientValue}>{item.protein}g</Text>
                                  <Text style={styles.nutrientLabel}>蛋白質</Text>
                                </View>
                                <View style={styles.nutrientBadge}>
                                  <Text style={styles.nutrientValue}>{item.carbs}g</Text>
                                  <Text style={styles.nutrientLabel}>碳水</Text>
                                </View>
                                <View style={styles.nutrientBadge}>
                                  <Text style={styles.nutrientValue}>{item.fat}g</Text>
                                  <Text style={styles.nutrientLabel}>脂肪</Text>
                                </View>
                                <View style={styles.nutrientBadge}>
                                  <Text style={styles.nutrientValue}>{item.sodium} <Text style={styles.nutrientUnit}>mg</Text></Text>
                                  <Text style={styles.nutrientLabel}>鈉</Text>
                                </View>
                              </View>

                              {/* 安全性警告標記 */}
                              {!safety.isSafe && (
                                <View style={styles.safetyAlertContainer}>
                                  <Ionicons name="warning-outline" size={14} color={Palette.status.error} />
                                  <Text style={styles.safetyAlertText}>{safety.reasons.join(' ｜ ')}</Text>
                                </View>
                              )}
                            </View>
                          );
                        })
                      ) : (
                        <Text style={styles.noMenuText}>目前此餐廳尚無任何菜單項目，請點擊上方更新菜單資料。</Text>
                      )}
                    </View>
                  )}
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>

      {/* 1. 一鍵飲食記錄 Modal */}
      <Modal
        visible={recordModalVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setRecordModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>記錄餐點至今日飲食</Text>
            {selectedItem && (
              <View style={styles.modalSelectedPreview}>
                <Text style={styles.modalSelectedName}>{selectedItem.item_name || selectedItem.name}</Text>
                <Text style={styles.modalSelectedMeta}>
                  來自：{selectedItem.restaurant_name} ｜ 熱量：{selectedItem.calories} kcal
                </Text>
              </View>
            )}

            <Text style={styles.modalLabel}>選擇餐點時段</Text>
            <View style={styles.mealTypeGrid}>
              {(['早餐', '午餐', '晚餐', '點心'] as const).map((type) => {
                const isSelected = selectedMealType === type;
                return (
                  <TouchableOpacity
                    key={type}
                    style={[styles.mealTypeOption, isSelected && styles.mealTypeOptionSelected]}
                    onPress={() => setSelectedMealType(type)}
                  >
                    <Text style={[styles.mealTypeOptionText, isSelected && styles.mealTypeOptionTextSelected]}>
                      {type === '早餐' ? '🍳 早餐' : type === '午餐' ? '🍱 午餐' : type === '晚餐' ? '🍛 晚餐' : type === '點心' ? '🍰 點心' : type}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalCancelBtn]}
                onPress={() => setRecordModalVisible(false)}
                disabled={recording}
              >
                <Text style={styles.modalCancelBtnText}>取消</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalConfirmBtn]}
                onPress={handleAddRecord}
                disabled={recording}
              >
                {recording ? (
                  <ActivityIndicator size="small" color={Palette.text.inverse} />
                ) : (
                  <Text style={styles.modalConfirmBtnText}>確認記錄</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* 2. AI 建立/更新菜單 Modal */}
      <Modal
        visible={aiModalVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setAiModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { maxHeight: '85%', width: '90%' }]}>
            <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: Spacing.xl }}>
              <View style={styles.modalHeaderRow}>
                <Ionicons name="sparkles" size={20} color={Palette.accent.green} />
                <Text style={[styles.modalTitle, { flex: 1, marginLeft: 6 }]}>AI 智能菜單生成與更新</Text>
                <TouchableOpacity onPress={() => setAiModalVisible(false)}>
                  <Ionicons name="close" size={24} color={Palette.text.tertiary} />
                </TouchableOpacity>
              </View>

              <Text style={styles.aiNotice}>
                請填寫以下資訊，AI 廚師將結合網路公開資料或您提供的內容，自動產生經典菜色以及每道菜的熱量、蛋白質與鈉含量等營養素結構！
              </Text>

              {/* 輸入欄 */}
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>餐廳名稱 *</Text>
                <TextInput
                  style={styles.formInput}
                  placeholder="例如：小智牛肉麵"
                  placeholderTextColor={Palette.text.muted}
                  value={aiRestaurantName}
                  onChangeText={setAiRestaurantName}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>餐廳地址</Text>
                <TextInput
                  style={styles.formInput}
                  placeholder="例如：台北市大安區新生南路一段"
                  placeholderTextColor={Palette.text.muted}
                  value={aiAddress}
                  onChangeText={setAiAddress}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>菜單網址 (選填 — AI 將嘗試連線爬取)</Text>
                <TextInput
                  style={styles.formInput}
                  placeholder="https://example.com/menu"
                  placeholderTextColor={Palette.text.muted}
                  value={aiMenuUrl}
                  onChangeText={setAiMenuUrl}
                  autoCapitalize="none"
                  keyboardType="url"
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>菜單文字 (選填 — 優先使用！直接手動貼上)</Text>
                <TextInput
                  style={[styles.formInput, styles.formTextArea]}
                  placeholder="例如：&#10;招牌牛肉麵 160元&#10;紅油抄手 80元&#10;燙青菜 40元"
                  placeholderTextColor={Palette.text.muted}
                  value={aiMenuText}
                  onChangeText={setAiMenuText}
                  multiline
                  numberOfLines={5}
                />
              </View>

              <View style={styles.modalActions}>
                <TouchableOpacity
                  style={[styles.modalButton, styles.modalCancelBtn]}
                  onPress={() => setAiModalVisible(false)}
                  disabled={aiLoading}
                >
                  <Text style={styles.modalCancelBtnText}>取消</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.modalButton, styles.modalConfirmBtn, { backgroundColor: Palette.accent.green }]}
                  onPress={handleAiSubmit}
                  disabled={aiLoading}
                >
                  {aiLoading ? (
                    <ActivityIndicator size="small" color={Palette.text.inverse} />
                  ) : (
                    <Text style={styles.modalConfirmBtnText}>由 AI 解析並儲存</Text>
                  )}
                </TouchableOpacity>
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  scrollContent: {
    paddingBottom: Spacing['3xl'],
  },
  centerContainer: {
    paddingVertical: Spacing['5xl'],
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: {
    ...Typography.caption,
    color: Palette.text.secondary,
    marginTop: Spacing.md,
  },
  searchContainer: {
    flexDirection: 'row',
    gap: Spacing.sm,
    marginBottom: Spacing.lg,
  },
  searchInputWrapper: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    paddingHorizontal: Spacing.md,
    height: 48,
    ...Shadows.soft,
  },
  searchIcon: {
    marginRight: Spacing.sm,
  },
  searchInput: {
    flex: 1,
    ...Typography.body,
    color: Palette.text.primary,
    padding: 0,
  },
  searchButton: {
    backgroundColor: Palette.accent.green,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.xl,
    justifyContent: 'center',
    alignItems: 'center',
    height: 48,
    ...Shadows.soft,
  },
  searchButtonText: {
    ...Typography.bodyBold,
    color: Palette.text.inverse,
  },
  quickAddCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Palette.bg.mint,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: 'rgba(31,157,114,0.18)',
  },
  quickAddText: {
    flex: 1,
    ...Typography.caption,
    color: Palette.accent.green,
    fontWeight: '700',
    marginHorizontal: Spacing.sm,
  },
  emptyContainer: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    padding: Spacing['2xl'],
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    marginTop: Spacing.xl,
    ...Shadows.soft,
  },
  emptyIconCircle: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: Palette.bg.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: Spacing.lg,
  },
  emptyTitle: {
    ...Typography.h2,
    color: Palette.text.primary,
    marginBottom: Spacing.xs,
  },
  emptySubtitle: {
    ...Typography.caption,
    color: Palette.text.tertiary,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: Spacing.xl,
  },
  aiGenerateButton: {
    flexDirection: 'row',
    backgroundColor: Palette.accent.purple,
    borderRadius: Radius.lg,
    paddingVertical: Spacing.md,
    paddingHorizontal: Spacing.xl,
    alignItems: 'center',
    ...Shadows.glow(Palette.accent.purple),
  },
  aiGenerateButtonText: {
    ...Typography.bodyBold,
    color: Palette.text.inverse,
  },
  restaurantList: {
    gap: Spacing.md,
  },
  restaurantCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    overflow: 'hidden',
    ...Shadows.soft,
  },
  restaurantCardExpanded: {
    borderColor: Palette.border.medium,
    ...Shadows.card,
  },
  restaurantHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: Spacing.lg,
    gap: Spacing.md,
  },
  restaurantHeaderInfo: {
    flex: 1,
    gap: 4,
  },
  restaurantName: {
    ...Typography.h3,
    color: Palette.text.primary,
  },
  restaurantAddress: {
    ...Typography.caption,
    color: Palette.text.tertiary,
  },
  tagRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: Spacing.xs,
  },
  tagPill: {
    backgroundColor: Palette.bg.primary,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderWidth: 0.5,
    borderColor: Palette.border.subtle,
  },
  tagPillText: {
    fontSize: 10,
    fontWeight: '700',
    color: Palette.text.tertiary,
  },
  menuContainer: {
    borderTopWidth: 1,
    borderTopColor: Palette.border.subtle,
    backgroundColor: Palette.bg.wash,
    padding: Spacing.lg,
    gap: Spacing.md,
  },
  menuActionBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: Spacing.xs,
  },
  menuTitle: {
    ...Typography.bodyBold,
    color: Palette.text.primary,
  },
  updateMenuBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Palette.bg.mint,
    borderRadius: Radius.sm,
    paddingVertical: 4,
    paddingHorizontal: Spacing.sm,
    borderWidth: 0.5,
    borderColor: 'rgba(31,157,114,0.3)',
  },
  updateMenuBtnText: {
    fontSize: 11,
    fontWeight: '700',
    color: Palette.accent.green,
  },
  noMenuText: {
    ...Typography.caption,
    color: Palette.text.muted,
    textAlign: 'center',
    paddingVertical: Spacing.xl,
  },
  menuItemCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.md,
    gap: Spacing.sm,
    ...Shadows.soft,
  },
  menuItemTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  menuItemTitleBlock: {
    flex: 1,
    gap: 2,
  },
  menuItemName: {
    ...Typography.bodyBold,
    color: Palette.text.primary,
  },
  menuItemPrice: {
    ...Typography.caption,
    color: Palette.accent.green,
    fontWeight: '700',
  },
  recordButton: {
    flexDirection: 'row',
    backgroundColor: Palette.accent.green,
    borderRadius: Radius.sm,
    paddingVertical: 6,
    paddingHorizontal: Spacing.md,
    alignItems: 'center',
  },
  recordButtonText: {
    fontSize: 12,
    fontWeight: '700',
    color: Palette.text.inverse,
  },
  nutritionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: Palette.bg.primary,
    borderRadius: Radius.sm,
    padding: Spacing.sm,
  },
  nutrientBadge: {
    alignItems: 'center',
    flex: 1,
  },
  nutrientValue: {
    fontSize: 12,
    fontWeight: '800',
    color: Palette.text.primary,
  },
  nutrientUnit: {
    fontSize: 9,
    fontWeight: '500',
  },
  nutrientLabel: {
    fontSize: 9,
    fontWeight: '700',
    color: Palette.text.muted,
    marginTop: 2,
  },
  safetyAlertContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(226,85,85,0.08)',
    borderRadius: Radius.sm,
    paddingVertical: 4,
    paddingHorizontal: Spacing.sm,
    gap: 4,
  },
  safetyAlertText: {
    fontSize: 11,
    fontWeight: '700',
    color: Palette.status.error,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: Palette.overlay,
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalCard: {
    width: '85%',
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    padding: Spacing.xl,
    gap: Spacing.lg,
    ...Shadows.card,
  },
  modalHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: Spacing.xs,
  },
  modalTitle: {
    ...Typography.h2,
    color: Palette.text.primary,
  },
  modalSelectedPreview: {
    backgroundColor: Palette.bg.primary,
    borderRadius: Radius.md,
    padding: Spacing.md,
    gap: 4,
  },
  modalSelectedName: {
    ...Typography.bodyBold,
    color: Palette.text.primary,
  },
  modalSelectedMeta: {
    ...Typography.caption,
    color: Palette.text.tertiary,
  },
  modalLabel: {
    ...Typography.caption,
    color: Palette.text.secondary,
    fontWeight: '700',
  },
  mealTypeGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.sm,
  },
  mealTypeOption: {
    flex: 1,
    minWidth: '45%',
    backgroundColor: Palette.bg.primary,
    borderRadius: Radius.md,
    paddingVertical: Spacing.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  mealTypeOptionSelected: {
    backgroundColor: Palette.bg.mint,
    borderColor: Palette.accent.green,
  },
  mealTypeOptionText: {
    ...Typography.body,
    color: Palette.text.secondary,
  },
  mealTypeOptionTextSelected: {
    fontWeight: '700',
    color: Palette.accent.green,
  },
  modalActions: {
    flexDirection: 'row',
    gap: Spacing.md,
    marginTop: Spacing.md,
  },
  modalButton: {
    flex: 1,
    height: 48,
    borderRadius: Radius.lg,
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalCancelBtn: {
    backgroundColor: Palette.bg.primary,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  modalCancelBtnText: {
    ...Typography.bodyBold,
    color: Palette.text.secondary,
  },
  modalConfirmBtn: {
    backgroundColor: Palette.accent.blue,
  },
  modalConfirmBtnText: {
    ...Typography.bodyBold,
    color: Palette.text.inverse,
  },
  aiNotice: {
    ...Typography.caption,
    color: Palette.text.secondary,
    lineHeight: 18,
    marginBottom: Spacing.sm,
  },
  inputGroup: {
    gap: 6,
    marginBottom: Spacing.md,
  },
  inputLabel: {
    ...Typography.caption,
    color: Palette.text.primary,
    fontWeight: '700',
  },
  formInput: {
    backgroundColor: Palette.bg.primary,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    paddingHorizontal: Spacing.md,
    height: 44,
    ...Typography.body,
    color: Palette.text.primary,
  },
  formTextArea: {
    height: 100,
    paddingTop: Spacing.md,
    textAlignVertical: 'top',
  },
});
