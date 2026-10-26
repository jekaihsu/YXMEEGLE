import assert from 'node:assert/strict';
import {formatPlanQuantity} from './src/caseDetailView.ts';
assert.equal(formatPlanQuantity('-0.000'),'0');
assert.equal(formatPlanQuantity('-0E+1'),'0');
assert.equal(formatPlanQuantity('-1'),'—');
assert.equal(formatPlanQuantity('1.2300'),'1.23');
