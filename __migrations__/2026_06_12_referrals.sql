-- Arc 25 Stream 4 — practitioner referral loop.
-- referral_code: the practitioner's permanent shareable code (generated
-- lazily by GET /access/referrals/me). referred_by/referred_at: signup
-- attribution, written once by POST /access/referrals/redeem.
-- Admission during invite-only rides the existing invited_via_token
-- column (sentinel value 'ref:<code>') — no schema change needed there.
-- Service-role access only (backend); no RLS policy changes.

alter table user_profiles add column if not exists referral_code text;
alter table user_profiles add column if not exists referred_by uuid;
alter table user_profiles add column if not exists referred_at timestamptz;

create unique index if not exists uq_user_profiles_referral_code
  on user_profiles (referral_code) where referral_code is not null;
create index if not exists idx_user_profiles_referred_by
  on user_profiles (referred_by) where referred_by is not null;
