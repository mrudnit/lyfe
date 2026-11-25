-- Reset one guest to a clean start: no requested tracks, likes, dislikes,
-- boosts, points, door rewards, «Взлом» runs or gang. Kept: the account,
-- its LYFE number, tickets / LYFE PASS and check-ins.
--
-- Paste into psql (Railway → Postgres → Console → psql -U "$POSTGRES_USER" -d "$POSTGRES_DB").
-- Change the LYFE number on the first line. All or nothing: any error and
-- nothing is changed.

\set lyfe 0001

BEGIN;

CREATE TEMP TABLE reset_me ON COMMIT DROP AS
  SELECT id, lyfe_id, first_name, tg_username FROM users WHERE lyfe_id = :'lyfe';
SELECT 'resetting' AS what, * FROM reset_me;

-- tracks this person touched, to recount them afterwards
CREATE TEMP TABLE reset_tracks ON COMMIT DROP AS
  SELECT event_track_id AS id FROM track_requests WHERE user_id IN (SELECT id FROM reset_me)
  UNION SELECT event_track_id FROM track_votes WHERE user_id IN (SELECT id FROM reset_me)
  UNION SELECT ref_id FROM point_transactions
        WHERE user_id IN (SELECT id FROM reset_me) AND reason_code = 'BOOST' AND ref_type = 'event_track';

-- take their boosts off the tracks
UPDATE event_tracks e SET boost_points = GREATEST(0, e.boost_points - b.spent)
  FROM (SELECT ref_id, -SUM(delta) AS spent FROM point_transactions
        WHERE user_id IN (SELECT id FROM reset_me) AND reason_code = 'BOOST' AND ref_type = 'event_track'
        GROUP BY ref_id) b
  WHERE e.id = b.ref_id;

DELETE FROM track_votes        WHERE user_id IN (SELECT id FROM reset_me);
DELETE FROM track_requests     WHERE user_id IN (SELECT id FROM reset_me);
DELETE FROM point_transactions WHERE user_id IN (SELECT id FROM reset_me);
DELETE FROM reward_redemptions WHERE user_id IN (SELECT id FROM reset_me);
DELETE FROM game_sessions      WHERE user_id IN (SELECT id FROM reset_me);

-- gang: leave it; the next one in becomes leader, an empty gang goes away
CREATE TEMP TABLE reset_gangs ON COMMIT DROP AS
  SELECT gang_id AS id FROM gang_members WHERE user_id IN (SELECT id FROM reset_me);
DELETE FROM gang_members WHERE user_id IN (SELECT id FROM reset_me);
DELETE FROM gangs g WHERE g.id IN (SELECT id FROM reset_gangs)
  AND NOT EXISTS (SELECT 1 FROM gang_members m WHERE m.gang_id = g.id);
UPDATE gang_members m SET role = 'leader'
  WHERE m.id IN (
    SELECT DISTINCT ON (gang_id) id FROM gang_members
    WHERE gang_id IN (SELECT id FROM reset_gangs)
      AND gang_id NOT IN (SELECT gang_id FROM gang_members WHERE role = 'leader')
    ORDER BY gang_id, joined_at, id);

-- recount the tracks; a track nobody requests any more leaves the top
UPDATE event_tracks e SET
  requests_count = (SELECT count(*) FROM track_requests r WHERE r.event_track_id = e.id),
  votes_count    = (SELECT count(*) FROM track_votes v WHERE v.event_track_id = e.id AND v.value = 1),
  dislikes_count = (SELECT count(*) FROM track_votes v WHERE v.event_track_id = e.id AND v.value = -1)
  WHERE e.id IN (SELECT id FROM reset_tracks);
DELETE FROM event_tracks e WHERE e.id IN (SELECT id FROM reset_tracks)
  AND e.requests_count = 0 AND e.played_at IS NULL;

SELECT
  (SELECT count(*) FROM track_requests     WHERE user_id IN (SELECT id FROM reset_me)) AS tracks,
  (SELECT count(*) FROM track_votes        WHERE user_id IN (SELECT id FROM reset_me)) AS likes_dislikes,
  (SELECT coalesce(sum(delta), 0) FROM point_transactions WHERE user_id IN (SELECT id FROM reset_me)) AS points,
  (SELECT count(*) FROM game_sessions      WHERE user_id IN (SELECT id FROM reset_me)) AS runs,
  (SELECT count(*) FROM gang_members       WHERE user_id IN (SELECT id FROM reset_me)) AS gang;

COMMIT;
