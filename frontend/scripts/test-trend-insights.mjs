import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CALORIE_GOAL_LOWER_RATIO,
  CALORIE_GOAL_UPPER_RATIO,
  buildTrendInsights,
  classifyCalories,
  findSodiumOverDays,
} from '../lib/trend-insights.ts';

const NO_SODIUM_OVER_MESSAGE = '近期鈉攝取沒有明顯超標日，維持目前記錄習慣。';

function day(date, calories, sodium = 1200) {
  return {
    date,
    record_count: 3,
    calories,
    protein: 60,
    carbs: 200,
    sugar: 10,
    fat: 50,
    saturated_fat: 10,
    trans_fat: 0,
    fiber: 15,
    sodium,
  };
}

function summaryOf(daily) {
  return {
    avg_calories: Math.round(daily.reduce((sum, item) => sum + item.calories, 0) / daily.length),
    recorded_days: daily.length,
    total_records: daily.length * 3,
  };
}

function insightsFor(daily, calorieTarget = 2000, sodiumTarget = 2000) {
  return buildTrendInsights(summaryOf(daily), daily, calorieTarget, sodiumTarget);
}

function latestCalorieInsight(calories, calorieTarget) {
  return insightsFor([day('2026-06-30', calories)], calorieTarget)[2];
}

test('uses the same 85%-115% band as the daily calorie chart', () => {
  assert.equal(CALORIE_GOAL_LOWER_RATIO, 0.85);
  assert.equal(CALORIE_GOAL_UPPER_RATIO, 1.15);
  assert.equal(classifyCalories(1699, 2000), 'low');
  assert.equal(classifyCalories(1700, 2000), 'on-target');
  assert.equal(classifyCalories(2300, 2000), 'on-target');
  assert.equal(classifyCalories(2301, 2000), 'high');
});

test('75% of the target is low, not close to the target', () => {
  assert.equal(latestCalorieInsight(1500, 2000), '最近一天熱量偏低，距離目標仍差 500 kcal。');
});

test('the live hypertension case (1,240 of 1,648 kcal) is low', () => {
  assert.equal(latestCalorieInsight(1240, 1648), '最近一天熱量偏低，距離目標仍差 408 kcal。');
});

test('100% of the target is close to the target', () => {
  assert.equal(latestCalorieInsight(2000, 2000), '最近一天的熱量接近個人目標，可觀察蛋白質與纖維是否同步達標。');
});

test('120% of the target is high and says by how much', () => {
  const insight = latestCalorieInsight(2400, 2000);
  assert.match(insight, /^最近一天熱量偏高，超過目標 400 kcal/);
});

test('six over-limit days: gives the count and names the worst day', () => {
  const daily = [
    day('2026-06-28', 1800, 2100),
    day('2026-06-29', 1800, 2730),
    day('2026-06-30', 1800, 2450),
    day('2026-07-01', 1800, 1500),
    day('2026-07-02', 1800, 2200),
    day('2026-07-03', 1800, 2050),
    day('2026-07-04', 1800, 2600),
  ];
  const insight = insightsFor(daily)[1];
  assert.equal(
    insight,
    '近 7 天有 6 天鈉超過每日上限 2,000 mg，最高是 06-29 的 2,730 mg，建議檢查加工食品與外食比例。'
  );
});

test('one over-limit day is named without calling it the highest', () => {
  const daily = [day('2026-06-28', 1800, 1500), day('2026-06-29', 1800, 2730)];
  assert.equal(
    insightsFor(daily)[1],
    '近 2 天有 1 天鈉超過每日上限 2,000 mg，是 06-29 的 2,730 mg，建議檢查加工食品與外食比例。'
  );
});

test('no over-limit day keeps the existing message', () => {
  const daily = [day('2026-06-28', 1800, 2000), day('2026-06-29', 1800, 1400)];
  assert.equal(insightsFor(daily)[1], NO_SODIUM_OVER_MESSAGE);
});

test('uses the sodium limit it is given (e.g. 1,500 mg for kidney disease)', () => {
  const daily = [day('2026-06-28', 1800, 1400), day('2026-06-29', 1800, 1800)];
  assert.equal(findSodiumOverDays(daily, 1500).length, 1);
  assert.equal(
    insightsFor(daily, 2000, 1500)[1],
    '近 2 天有 1 天鈉超過每日上限 1,500 mg，是 06-29 的 1,800 mg，建議檢查加工食品與外食比例。'
  );
  assert.equal(insightsFor(daily, 2000, 2000)[1], NO_SODIUM_OVER_MESSAGE);
});

test('no history returns the empty-state hint only', () => {
  assert.deepEqual(buildTrendInsights({}, [], 2000, 2000), ['尚無歷史紀錄，先從掃描或手動加入餐點開始建立趨勢。']);
});
