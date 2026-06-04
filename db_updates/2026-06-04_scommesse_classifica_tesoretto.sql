-- Aggiornamento manuale del 04/06/2026.
-- Il file è idempotente: può essere rieseguito senza duplicare le scommesse.

INSERT INTO predictions (user_id, username, prediction, date) VALUES
    (861107469, 'Henifax', 2.0, '2026-06-04'),
    (68001743, 'Spall_one', -0.58, '2026-06-04')
ON CONFLICT(user_id, date) DO UPDATE SET
    username = excluded.username,
    prediction = excluded.prediction;

INSERT INTO balances (user_id, username, balance) VALUES
    (68001743, 'Spall_one', 8861.5),
    (1384243346, 'aw3tr4n4', 8519.15),
    (5178397412, 'Palledidiamante', 6182.7),
    (1415311504, 'Tosa89', 5040.85),
    (1094510891, 'LorenzoPiodi', 4952.6),
    (1731769871, 'DuxMeaLux1', 3168.25),
    (337185860, 'Profeta_Nick_1', 1173.65),
    (545408682, 'Darione81', 422.15),
    (1141167031, 'iEnz95', 243.8),
    (1614910657, 'nandofri', -188.66),
    (48769893, 'antiulisse', -572.75),
    (5028744971, 'Asdomare1', -583.2),
    (8444135023, 'NickAngel', -826.45),
    (425368353, 'MajesticGoldenPenis69', -949.95),
    (1685735480, 'Bighead1983', -1347.7),
    (2013733099, 'Titanfist', -2886.5),
    (569520278, 'Iceman198222', -2890.3),
    (170495047, 'gigixy91', -2932.45),
    (554433221, 'rustincohle03', -3253.35),
    (1667436384, 'stefanostt', -4382.25),
    (861107469, 'Henifax', -8536.55),
    (136029918, 'Padrennatura', -10155.85)
ON CONFLICT(user_id) DO UPDATE SET
    username = excluded.username,
    balance = excluded.balance;

INSERT INTO weekly_pot (week_start, amount) VALUES ('2026-06-01', 570)
ON CONFLICT(week_start) DO UPDATE SET
    amount = excluded.amount;
