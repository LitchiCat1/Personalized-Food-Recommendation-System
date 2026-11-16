import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const backend = fileURLToPath(new URL('../../../backend/', import.meta.url));
const fixture = spawnSync('python', ['-c', `
import json, socket, sys
sys.path.insert(0, sys.argv[1])
socket.socket = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('network disabled'))
from services.record_nutrition_service import normalize_v2_record, aggregate_record_coverage
from services.history_service import build_history_response
keys = ('calories','protein','carbs','sugar','fat','saturated_fat','trans_fat','fiber','sodium')
cells = dict(calories=100,protein=4,carbs=10,sugar=1,fat=5,saturated_fat=1,trans_fat=0,fiber=2,sodium=0)
def record(name, *, nutrients=cells, unknown=False, extra=False, excluded=False, date='2026-11-14'):
    food = dict(item_id='food-a',name='rice',weight_g=100,portion_source='user_weighed')
    if not unknown: food['user_entered_nutrients'] = nutrients
    if excluded: food.update(included=False,exclusion_reason='not_consumed')
    foods = [food]
    if extra: foods.append(dict(item_id='food-b',name='sauce',weight_g=None,portion_source='unknown'))
    payload = dict(nutrition_contract_version=2,foods=foods)
    return dict(normalize_v2_record(payload),user_id='read-user',client_record_id=name,
                timestamp=date+'T00:03:00+08:00',meal_type='breakfast',source='camera')
complete = record('complete')
partial = record('partial',extra=True)
bounded = record('bounded',nutrients=dict(cells,sugar=dict(value='0.1',unit='g',comparison='less_than')))
unknown = record('unknown',unknown=True)
excluded = record('excluded',excluded=True)
legacy = dict(user_id='read-user',client_record_id='legacy',timestamp='2026-11-14T00:03:00+08:00',
              foods=[dict(name='legacy',calories=999)],total_calories=50,total_sodium=0)
class Storage:
    def __init__(self, records): self.records=records
    def get_history(self,*args,**kwargs):
        result=[]
        for date in sorted(set(r['timestamp'][:10] for r in self.records)):
            records=[r for r in self.records if r['timestamp'][:10]==date]
            coverage=aggregate_record_coverage(records)
            result.append(dict(date=date,record_count=len(records),nutrition_coverage=coverage,
                               **{k:coverage['nutrients'][k]['known_sum'] for k in keys}))
        return result
def history(records): return build_history_response(Storage(records),'read-user',7,nutrition_contract_version=2)
previous = dict(complete,timestamp='2026-11-13T23:59:00+08:00')
decimal_a = record('decimal-a',nutrients=dict(cells,sodium=0.1),date='2026-11-13')
decimal_b = record('decimal-b',nutrients=dict(cells,sodium=0.2))
print(json.dumps(dict(complete=complete,partial=partial,bounded=bounded,unknown=unknown,excluded=excluded,
                     legacy=legacy,history=history([partial,legacy]),emptyHistory=history([]),
                     excludedHistory=history([previous,excluded]),decimalHistory=history([decimal_a,decimal_b]))))
`, path.resolve(backend)], {
  encoding: 'utf8', env: { ...process.env, NUTRILENS_SKIP_LOCAL_ENV: '1', PYTHONIOENCODING: 'utf-8' },
});
assert.equal(fixture.status, 0, fixture.stderr);
export const nutritionReadFixtures = JSON.parse(fixture.stdout);
