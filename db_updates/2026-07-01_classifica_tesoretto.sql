-- Aggiornamento manuale del 01/07/2026.
-- Il file è idempotente.

INSERT INTO predictions (user_id, username, prediction, date) VALUES
    (545408682, 'Darione81', -0.69, '2026-06-30'),
    (68001743, 'Spall_one', 0.56, '2026-06-30'),
    (861107469, 'Henifax', 0.74, '2026-06-30'),
    (1415311504, 'Tosa89', 1.00, '2026-06-30')
ON CONFLICT(user_id, date) DO UPDATE SET
    username = excluded.username,
    prediction = excluded.prediction;


INSERT INTO balances (user_id, username, balance) VALUES
    (68001743, 'Spall_one', 9642.2),
    (1384243346, 'aw3tr4n4', 8203.95),
    (5178397412, 'Palledidiamante', 7085.4),
    (1415311504, 'Tosa89', 4629.55),
    (1094510891, 'LorenzoPiodi', 4602.55),
    (1731769871, 'DuxMeaLux1', 3008.25),
    (337185860, 'Profeta_Nick_1', 1072.6),
    (545408682, 'Darione81', 201.0),
    (1141167031, 'iEnz95', 93.8),
    (1614910657, 'nandofri', -45.56),
    (48769893, 'antiulisse', -732.75),
    (1685735480, 'Bighead1983', -742.3),
    (5028744971, 'Asdomare1', -743.2),
    (8444135023, 'NickAngel', -986.45),
    (425368353, 'MajesticGoldenPenis69', -1109.95),
    (2013733099, 'Titanfist', -3046.5),
    (569520278, 'Iceman198222', -3050.3),
    (170495047, 'gigixy91', -3092.45),
    (554433221, 'rustincohle03', -3413.35),
    (1667436384, 'stefanostt', -4542.25),
    (861107469, 'Henifax', -7249.7),
    (136029918, 'Padrennatura', -10315.85)
ON CONFLICT(user_id) DO UPDATE SET
    username = excluded.username,
    balance = excluded.balance;

-- Rimuove tesoretti storici già superati
DELETE FROM weekly_pot WHERE week_start < '2026-06-29';

INSERT INTO weekly_pot (week_start, amount) VALUES
    ('2026-06-29', 160.00)
ON CONFLICT(week_start) DO UPDATE SET
    amount = excluded.amount;
