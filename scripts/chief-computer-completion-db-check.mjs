import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {PGlite}=await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db=new PGlite();
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE TABLE businesses(id uuid PRIMARY KEY,settings jsonb DEFAULT '{}');
CREATE FUNCTION is_business_owner(uuid) RETURNS boolean LANGUAGE sql AS 'SELECT false';
CREATE FUNCTION is_business_member(uuid) RETURNS boolean LANGUAGE sql AS 'SELECT false';
CREATE TABLE offerings(id uuid PRIMARY KEY,business_id uuid,reorder_pending_at timestamptz);
CREATE TABLE suppliers(id uuid PRIMARY KEY,business_id uuid,notes text,last_ordered_at timestamptz);
CREATE TABLE business_expenses(id uuid PRIMARY KEY,business_id uuid,amount numeric,category text,
 subcategory text,description text,date date,vendor text,receipt_path text,notes text);
CREATE TABLE accounting_periods(business_id uuid,status text,period_start date,period_end date);
CREATE TABLE chief_undo_log(id uuid PRIMARY KEY,business_id uuid,user_id uuid,action_type text,
 action_json jsonb,result_json jsonb,status text,created_at timestamptz);`);
await db.exec(readFileSync('supabase/APPLY-2026-09-12-chief-computer.sql','utf8'));
const migration=readFileSync('supabase/APPLY-2026-09-12-chief-computer-completion.sql','utf8');
await db.exec(migration); await db.exec(migration);
await db.query('INSERT INTO businesses(id) VALUES($1),($2)',[id(1),id(9)]);
await db.query('INSERT INTO offerings(id,business_id) VALUES($1,$2)',[id(3),id(1)]);
await db.query('INSERT INTO suppliers(id,business_id,notes) VALUES($1,$2,$3)',[id(4),id(1),'Preserve this note']);
const plan={supplier:{id:id(4),name:'Supplier'},items:[{offering_id:id(3),qty:1}],__submission_attempted_at:'2026-09-12T12:00:00Z'};
const receipt={order_number:'TEST-1',charged_cents:349,document_id:id(8),receipt_path:'private/receipt.pdf'};
await db.query(`INSERT INTO chief_errands(id,business_id,user_id,approved_by,kind,status,title,plan,receipt,hosts,
spend_limit_cents,observed_total_cents,finished_at) VALUES($1,$2,$3,$3,'reorder','done','Fixture',$4,$5,
ARRAY['supplier.test'],15000,349,'2026-09-12T12:00:00Z')`,[id(2),id(1),id(5),plan,receipt]);
const complete=(bid=id(1))=>db.query('SELECT to_jsonb(chief_errand_complete($1,$2)) AS r',[bid,id(2)]);
await assert.rejects(()=>complete(id(9)),/confirmed_order_required/);
for(const role of ['anon','authenticated']) {
 await db.exec('BEGIN; SET LOCAL ROLE '+role);
 await assert.rejects(()=>complete(),/permission denied/);
 await db.exec('ROLLBACK');
}
await db.query(`INSERT INTO accounting_periods VALUES($1,'closed','2026-09-01','2026-09-30')`,[id(1)]);
let result=(await complete()).rows[0].r;
assert.equal(result.plan.__inventory_done,true);
assert.equal(result.plan.__completion_done,false);
assert.match(result.error,/closed books/);
assert.equal((await db.query('SELECT * FROM business_expenses')).rows.length,0);
await complete();
assert.equal((await db.query('SELECT * FROM chief_undo_log')).rows.length,1);
await db.exec('DELETE FROM accounting_periods');
result=(await complete()).rows[0].r;
assert.equal(result.plan.__completion_done,true);
assert.equal(result.receipt.expense_id,id(2));
assert.equal(result.error,null);
await complete();
const expenses=(await db.query('SELECT * FROM business_expenses')).rows;
assert.equal(expenses.length,1);
assert.equal(Number(expenses[0].amount),3.49);
assert.equal(expenses[0].receipt_path,'private/receipt.pdf');
assert.equal((await db.query('SELECT notes FROM suppliers')).rows[0].notes,'Preserve this note\nChief order TEST-1');
const shown=()=>db.query('SELECT chief_errand_shown($1,$2) AS ok',[id(1),id(2)]);
assert.equal((await shown()).rows[0].ok,true);
assert.equal((await shown()).rows[0].ok,false);
await db.close();
console.log('Chief completion SQL passed: tenant/role denial, closed-period repair, one expense, one undo, preserved supplier notes and replay claim.');
