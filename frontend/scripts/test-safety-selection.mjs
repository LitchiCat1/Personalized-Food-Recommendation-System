import assert from 'node:assert/strict';
import test from 'node:test';
import { isSelected, toggleSelection } from '../lib/safety-selection.ts';

test('selects and deselects by id', () => {
  assert.deepEqual(toggleSelection([], 'hypertension', ['高血壓']), ['hypertension']);
  assert.deepEqual(toggleSelection(['hypertension'], 'hypertension', ['高血壓']), []);
});

test('deselects legacy chinese-label data instead of duplicating it', () => {
  // 舊資料存中文標籤時，點一下應該是「取消勾選」，不是變成兩個都留著。
  assert.deepEqual(toggleSelection(['高血壓'], 'hypertension', ['高血壓']), []);
  // 再點一次才重新勾選，而且只留新的 id 格式
  assert.deepEqual(toggleSelection([], 'hypertension', ['高血壓']), ['hypertension']);
});

test('keeps other conditions untouched', () => {
  assert.deepEqual(
    toggleSelection(['diabetes', '高血壓'], 'hypertension', ['高血壓']),
    ['diabetes']
  );
  assert.deepEqual(
    toggleSelection(['diabetes'], 'hypertension', ['高血壓']),
    ['diabetes', 'hypertension']
  );
});

test('accumulates conditions when toggled one after another', () => {
  // 逐一勾選三個病症，每一個都要留下來——先前連點會讓先勾的被蓋掉。
  let conditions = [];
  for (const id of ['hypertension', 'diabetes', 'gout']) {
    conditions = toggleSelection(conditions, id);
  }
  assert.deepEqual(conditions, ['hypertension', 'diabetes', 'gout']);
});

test('the checkbox state matches what toggling will do', () => {
  assert.equal(isSelected(['高血壓'], 'hypertension', ['高血壓']), true);
  assert.equal(isSelected(['hypertension'], 'hypertension', ['高血壓']), true);
  assert.equal(isSelected(['diabetes'], 'hypertension', ['高血壓']), false);
});
