-- Aggiornamento manuale del 26/06/2026.
-- Il file è idempotente: può essere rieseguito senza duplicare le scommesse.

INSERT INTO predictions (user_id, username, prediction, date) VALUES
    (861107469, 'Henifax', 2.23, '2026-06-26')
ON CONFLICT(user_id, date) DO UPDATE SET
    username = excluded.username,
    prediction = excluded.prediction;

INSERT INTO balances (user_id, username, balance) VALUES
    (68001743, 'Spall_one', 9579.85),
    (1384243346, 'aw3tr4n4', 8379.15),
    (5178397412, 'Palledidiamante', 6992.55),
    (1094510891, 'LorenzoPiodi', 4779.85),
    (1415311504, 'Tosa89', 4649.55),
    (1731769871, 'DuxMeaLux1', 3028.25),
    (337185860, 'Profeta_Nick_1', 1134.6),
    (1141167031, 'iEnz95', 113.8),
    (545408682, 'Darione81', 108.3),
    (1614910657, 'nandofri', 15.19),
    (1685735480, 'Bighead1983', -691.6),
    (48769893, 'antiulisse', -712.75),
    (5028744971, 'Asdomare1', -723.2),
    (8444135023, 'NickAngel', -966.45),
    (425368353, 'MajesticGoldenPenis69', -1089.95),
    (2013733099, 'Titanfist', -3026.5),
    (569520278, 'Iceman198222', -3030.3),
    (170495047, 'gigixy91', -3072.45),
    (554433221, 'rustincohle03', -3393.35),
    (1667436384, 'stefanostt', -4522.25),
    (861107469, 'Henifax', -9037.75),
    (136029918, 'Padrennatura', -10295.85)
ON CONFLICT(user_id) DO UPDATE SET
    username = excluded.username,
    balance = excluded.balance;

-- Rimuove tesoretti storici già superati: al 26/06/2026 devono restare
-- non assegnati solo quello della settimana precedente e quello corrente.
DELETE FROM weekly_pot WHERE week_start < '2026-06-15';

INSERT INTO weekly_pot (week_start, amount) VALUES
    ('2026-06-15', 700),
    ('2026-06-22', 710)
ON CONFLICT(week_start) DO UPDATE SET
    amount = excluded.amount;
