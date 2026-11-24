-- Dữ liệu mẫu cho iot_db (nạp SAU schema.sql)
--   mysql -u root -p iot_db < database/sample-data.sql
-- 3 tài khoản demo, mật khẩu chung: Demo@12345 (chỉ dùng để thử, đổi trước khi dùng thật)
--   demo_admin (Admin), demo_operator (Operator), demo_viewer (Viewer)
-- 2 chuồng, 2 thiết bị (1 ESP32 thật đã duyệt, 1 thiết bị mô phỏng đang chờ duyệt),
-- 24 giờ telemetry (10 phút/lần), 1 rule cảnh báo, cảnh báo, lịch sử lệnh, lịch cho ăn, audit log.
-- Không chứa mật khẩu MQTT thật: các cột hash là giá trị giả.
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS=0;

INSERT INTO users (id,username,password_hash,full_name,role,status,created_at) VALUES
('78d80cf1-09ee-5058-9659-b316e1dca476','demo_admin','$2b$12$gfyTxGfnXByShzxIgvdgg.L3MBsMB4ZtBNYLGKhPXcsCOp4FEvLEm','Hứa Xuân Thiệu','Admin','active','2026-11-20 08:00:00'),
('626aebc4-ce24-5f00-8b89-ee91738fd249','demo_operator','$2b$12$gfyTxGfnXByShzxIgvdgg.L3MBsMB4ZtBNYLGKhPXcsCOp4FEvLEm','Hoàng Anh Minh','Operator','active','2026-11-20 08:00:00'),
('2559ee59-8017-551c-af1d-961d0b227ede','demo_viewer','$2b$12$gfyTxGfnXByShzxIgvdgg.L3MBsMB4ZtBNYLGKhPXcsCOp4FEvLEm','Bùi Hồng Phong','Viewer','active','2026-11-20 08:00:00');

INSERT INTO barns (id,name,zone,animal_type) VALUES
('a3afb842-8624-57b8-89af-3a128de9a8a8','Chuồng gà 1','Khu A','Gà thịt'),
('066e5aeb-6c96-52b9-8205-480bc15761ad','Chuồng gà 2','Khu B','Gà đẻ');

INSERT INTO barn_assignments (user_id,barn_id,access_level) VALUES
('626aebc4-ce24-5f00-8b89-ee91738fd249','a3afb842-8624-57b8-89af-3a128de9a8a8','Operator'),
('2559ee59-8017-551c-af1d-961d0b227ede','a3afb842-8624-57b8-89af-3a128de9a8a8','Viewer'),
('2559ee59-8017-551c-af1d-961d0b227ede','066e5aeb-6c96-52b9-8205-480bc15761ad','Viewer');

INSERT INTO devices (device_id,hw_id,barn_id,name,model,fw,sensors,commands,interval_s,status,last_seen,registered_at,hw_version,mqtt_secret_hash) VALUES
('esp32-a0b1c2d3e4f5','a0b1c2d3e4f5','a3afb842-8624-57b8-89af-3a128de9a8a8','ESP32 chuồng 1','esp32','1.0.0','[{"name": "room", "driver": "dht11", "fields": {"temperature": "°C", "humidity": "%"}}]','["ping", "get_info", "read", "set_interval", "reboot", "relay_set", "servo_set", "feed", "mode_set"]',600,'online','2026-11-21 08:00:00','2026-11-20 08:00:00','esp32-devkit-v1','dbebedfd8d2927fca36edffa7dabd96663941cd7abcf07df70197873616902e3');

INSERT INTO registrations (hw_id,status,requested_at,updated_at,model,fw,sensors,commands,device_id,reason,password,password_hash) VALUES
('a0b1c2d3e4f5','approved','2026-11-20 07:55:00','2026-11-20 08:00:00','esp32','1.0.0','[{"name": "room", "driver": "dht11", "fields": {"temperature": "°C", "humidity": "%"}}]','["ping", "get_info", "read", "set_interval", "reboot", "relay_set", "servo_set", "feed", "mode_set"]','esp32-a0b1c2d3e4f5',NULL,NULL,'dbebedfd8d2927fca36edffa7dabd96663941cd7abcf07df70197873616902e3'),
('5f4e3d2c1b0a','pending','2026-11-21 07:30:00','2026-11-21 07:30:00','esp32-sim','1.0.0','[{"name": "room", "driver": "dht11", "fields": {"temperature": "°C", "humidity": "%"}}]','["ping", "get_info", "read", "set_interval", "reboot", "relay_set", "servo_set", "feed", "mode_set"]',NULL,NULL,NULL,'97f52c402bf00bc3ff50f290bd02690c958878909935862a196530fd23916739');

INSERT INTO device_configs (device_id,version,body,applied_at) VALUES
('esp32-a0b1c2d3e4f5',1,'{"interval_s": 600, "fan_on_c": 32, "fan_off_c": 30, "feed_max_per_day": 6}','2026-11-20 08:01:00');

INSERT INTO telemetry (device_id,received_at,device_ts,readings) VALUES
('esp32-a0b1c2d3e4f5','2026-11-20 08:00:00',1795136400,'{"values": {"room": {"temperature": 28.3, "humidity": 71}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 08:10:00',1795137000,'{"values": {"room": {"temperature": 28.3, "humidity": 70}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 08:20:00',1795137600,'{"values": {"room": {"temperature": 28.3, "humidity": 71}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 08:30:00',1795138200,'{"values": {"room": {"temperature": 28.3, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 08:40:00',1795138800,'{"values": {"room": {"temperature": 28.4, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 08:50:00',1795139400,'{"values": {"room": {"temperature": 28.6, "humidity": 67}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 09:00:00',1795140000,'{"values": {"room": {"temperature": 28.5, "humidity": 67}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 09:10:00',1795140600,'{"values": {"room": {"temperature": 28.9, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 09:20:00',1795141200,'{"values": {"room": {"temperature": 28.9, "humidity": 66}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 09:30:00',1795141800,'{"values": {"room": {"temperature": 29.1, "humidity": 67}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 09:40:00',1795142400,'{"values": {"room": {"temperature": 29.5, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 09:50:00',1795143000,'{"values": {"room": {"temperature": 30.1, "humidity": 66}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 10:00:00',1795143600,'{"values": {"room": {"temperature": 29.4, "humidity": 67}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 10:10:00',1795144200,'{"values": {"room": {"temperature": 30.4, "humidity": 65}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 10:20:00',1795144800,'{"values": {"room": {"temperature": 30.4, "humidity": 64}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 10:30:00',1795145400,'{"values": {"room": {"temperature": 30.8, "humidity": 66}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 10:40:00',1795146000,'{"values": {"room": {"temperature": 30.8, "humidity": 66}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 10:50:00',1795146600,'{"values": {"room": {"temperature": 30.3, "humidity": 64}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 11:00:00',1795147200,'{"values": {"room": {"temperature": 31.0, "humidity": 65}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 11:10:00',1795147800,'{"values": {"room": {"temperature": 30.7, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 11:20:00',1795148400,'{"values": {"room": {"temperature": 31.2, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 11:30:00',1795149000,'{"values": {"room": {"temperature": 31.4, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 11:40:00',1795149600,'{"values": {"room": {"temperature": 31.2, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 11:50:00',1795150200,'{"values": {"room": {"temperature": 30.9, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 12:00:00',1795150800,'{"values": {"room": {"temperature": 31.5, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 12:10:00',1795151400,'{"values": {"room": {"temperature": 32.1, "humidity": 64}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 12:20:00',1795152000,'{"values": {"room": {"temperature": 32.1, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 12:30:00',1795152600,'{"values": {"room": {"temperature": 31.2, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 12:40:00',1795153200,'{"values": {"room": {"temperature": 31.4, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 12:50:00',1795153800,'{"values": {"room": {"temperature": 31.7, "humidity": 60}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 13:00:00',1795154400,'{"values": {"room": {"temperature": 33.6, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 13:10:00',1795155000,'{"values": {"room": {"temperature": 34.2, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 13:20:00',1795155600,'{"values": {"room": {"temperature": 33.7, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 13:30:00',1795156200,'{"values": {"room": {"temperature": 33.5, "humidity": 59}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 13:40:00',1795156800,'{"values": {"room": {"temperature": 34.3, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 13:50:00',1795157400,'{"values": {"room": {"temperature": 33.7, "humidity": 59}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 14:00:00',1795158000,'{"values": {"room": {"temperature": 34.2, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 14:10:00',1795158600,'{"values": {"room": {"temperature": 33.6, "humidity": 60}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 14:20:00',1795159200,'{"values": {"room": {"temperature": 34.0, "humidity": 58}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 14:30:00',1795159800,'{"values": {"room": {"temperature": 32.1, "humidity": 59}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 14:40:00',1795160400,'{"values": {"room": {"temperature": 32.4, "humidity": 58}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 14:50:00',1795161000,'{"values": {"room": {"temperature": 32.6, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 15:00:00',1795161600,'{"values": {"room": {"temperature": 32.7, "humidity": 58}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 15:10:00',1795162200,'{"values": {"room": {"temperature": 32.7, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 15:20:00',1795162800,'{"values": {"room": {"temperature": 31.9, "humidity": 60}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 15:30:00',1795163400,'{"values": {"room": {"temperature": 32.7, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 15:40:00',1795164000,'{"values": {"room": {"temperature": 33.0, "humidity": 60}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 15:50:00',1795164600,'{"values": {"room": {"temperature": 32.5, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 16:00:00',1795165200,'{"values": {"room": {"temperature": 32.0, "humidity": 60}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 16:10:00',1795165800,'{"values": {"room": {"temperature": 31.8, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 16:20:00',1795166400,'{"values": {"room": {"temperature": 32.5, "humidity": 59}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 16:30:00',1795167000,'{"values": {"room": {"temperature": 31.9, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 16:40:00',1795167600,'{"values": {"room": {"temperature": 32.5, "humidity": 59}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 16:50:00',1795168200,'{"values": {"room": {"temperature": 31.9, "humidity": 61}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 17:00:00',1795168800,'{"values": {"room": {"temperature": 31.7, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 17:10:00',1795169400,'{"values": {"room": {"temperature": 32.2, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 17:20:00',1795170000,'{"values": {"room": {"temperature": 32.0, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 17:30:00',1795170600,'{"values": {"room": {"temperature": 31.5, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 17:40:00',1795171200,'{"values": {"room": {"temperature": 31.6, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 17:50:00',1795171800,'{"values": {"room": {"temperature": 31.1, "humidity": 64}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 18:00:00',1795172400,'{"values": {"room": {"temperature": 31.1, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 18:10:00',1795173000,'{"values": {"room": {"temperature": 31.9, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 18:20:00',1795173600,'{"values": {"room": {"temperature": 31.7, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 18:30:00',1795174200,'{"values": {"room": {"temperature": 31.1, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 18:40:00',1795174800,'{"values": {"room": {"temperature": 30.8, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 18:50:00',1795175400,'{"values": {"room": {"temperature": 30.8, "humidity": 65}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 19:00:00',1795176000,'{"values": {"room": {"temperature": 31.3, "humidity": 62}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 19:10:00',1795176600,'{"values": {"room": {"temperature": 30.8, "humidity": 64}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 19:20:00',1795177200,'{"values": {"room": {"temperature": 30.4, "humidity": 63}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 19:30:00',1795177800,'{"values": {"room": {"temperature": 30.2, "humidity": 64}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 19:40:00',1795178400,'{"values": {"room": {"temperature": 30.0, "humidity": 66}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 19:50:00',1795179000,'{"values": {"room": {"temperature": 29.9, "humidity": 65}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 20:00:00',1795179600,'{"values": {"room": {"temperature": 29.6, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 20:10:00',1795180200,'{"values": {"room": {"temperature": 29.6, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 20:20:00',1795180800,'{"values": {"room": {"temperature": 29.2, "humidity": 67}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 20:30:00',1795181400,'{"values": {"room": {"temperature": 29.5, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 20:40:00',1795182000,'{"values": {"room": {"temperature": 29.3, "humidity": 69}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 20:50:00',1795182600,'{"values": {"room": {"temperature": 29.3, "humidity": 66}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 21:00:00',1795183200,'{"values": {"room": {"temperature": 29.2, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 21:10:00',1795183800,'{"values": {"room": {"temperature": 28.5, "humidity": 69}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 21:20:00',1795184400,'{"values": {"room": {"temperature": 29.1, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 21:30:00',1795185000,'{"values": {"room": {"temperature": 28.1, "humidity": 68}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 21:40:00',1795185600,'{"values": {"room": {"temperature": 28.5, "humidity": 69}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 21:50:00',1795186200,'{"values": {"room": {"temperature": 27.7, "humidity": 70}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 22:00:00',1795186800,'{"values": {"room": {"temperature": 28.2, "humidity": 70}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 22:10:00',1795187400,'{"values": {"room": {"temperature": 27.8, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 22:20:00',1795188000,'{"values": {"room": {"temperature": 28.0, "humidity": 70}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 22:30:00',1795188600,'{"values": {"room": {"temperature": 27.5, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 22:40:00',1795189200,'{"values": {"room": {"temperature": 27.2, "humidity": 71}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 22:50:00',1795189800,'{"values": {"room": {"temperature": 27.1, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 23:00:00',1795190400,'{"values": {"room": {"temperature": 27.6, "humidity": 70}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 23:10:00',1795191000,'{"values": {"room": {"temperature": 26.7, "humidity": 71}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 23:20:00',1795191600,'{"values": {"room": {"temperature": 26.5, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 23:30:00',1795192200,'{"values": {"room": {"temperature": 26.9, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 23:40:00',1795192800,'{"values": {"room": {"temperature": 26.7, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-20 23:50:00',1795193400,'{"values": {"room": {"temperature": 26.1, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 00:00:00',1795194000,'{"values": {"room": {"temperature": 26.3, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 00:10:00',1795194600,'{"values": {"room": {"temperature": 26.8, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 00:20:00',1795195200,'{"values": {"room": {"temperature": 25.9, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 00:30:00',1795195800,'{"values": {"room": {"temperature": 25.8, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 00:40:00',1795196400,'{"values": {"room": {"temperature": 26.3, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 00:50:00',1795197000,'{"values": {"room": {"temperature": 26.4, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 01:00:00',1795197600,'{"values": {"room": {"temperature": 25.4, "humidity": 76}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 01:10:00',1795198200,'{"values": {"room": {"temperature": 26.4, "humidity": 76}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 01:20:00',1795198800,'{"values": {"room": {"temperature": 26.2, "humidity": 77}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 01:30:00',1795199400,'{"values": {"room": {"temperature": 25.5, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 01:40:00',1795200000,'{"values": {"room": {"temperature": 26.0, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 01:50:00',1795200600,'{"values": {"room": {"temperature": 26.2, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 02:00:00',1795201200,'{"values": {"room": {"temperature": 25.0, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 02:10:00',1795201800,'{"values": {"room": {"temperature": 25.5, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 02:20:00',1795202400,'{"values": {"room": {"temperature": 25.7, "humidity": 78}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 02:30:00',1795203000,'{"values": {"room": {"temperature": 26.0, "humidity": 78}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 02:40:00',1795203600,'{"values": {"room": {"temperature": 25.2, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 02:50:00',1795204200,'{"values": {"room": {"temperature": 25.0, "humidity": 78}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 03:00:00',1795204800,'{"values": {"room": {"temperature": 24.9, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 03:10:00',1795205400,'{"values": {"room": {"temperature": 25.7, "humidity": 78}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 03:20:00',1795206000,'{"values": {"room": {"temperature": 25.6, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 03:30:00',1795206600,'{"values": {"room": {"temperature": 25.0, "humidity": 77}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 03:40:00',1795207200,'{"values": {"room": {"temperature": 25.8, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 03:50:00',1795207800,'{"values": {"room": {"temperature": 26.2, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 04:00:00',1795208400,'{"values": {"room": {"temperature": 25.2, "humidity": 78}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 04:10:00',1795209000,'{"values": {"room": {"temperature": 25.1, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 04:20:00',1795209600,'{"values": {"room": {"temperature": 25.3, "humidity": 76}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 04:30:00',1795210200,'{"values": {"room": {"temperature": 25.8, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 04:40:00',1795210800,'{"values": {"room": {"temperature": 26.0, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 04:50:00',1795211400,'{"values": {"room": {"temperature": 26.5, "humidity": 76}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 05:00:00',1795212000,'{"values": {"room": {"temperature": 25.6, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 05:10:00',1795212600,'{"values": {"room": {"temperature": 25.8, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 05:20:00',1795213200,'{"values": {"room": {"temperature": 25.9, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 05:30:00',1795213800,'{"values": {"room": {"temperature": 26.2, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 05:40:00',1795214400,'{"values": {"room": {"temperature": 26.9, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 05:50:00',1795215000,'{"values": {"room": {"temperature": 26.1, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 06:00:00',1795215600,'{"values": {"room": {"temperature": 26.1, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 06:10:00',1795216200,'{"values": {"room": {"temperature": 26.5, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 06:20:00',1795216800,'{"values": {"room": {"temperature": 26.2, "humidity": 75}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 06:30:00',1795217400,'{"values": {"room": {"temperature": 26.6, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 06:40:00',1795218000,'{"values": {"room": {"temperature": 27.0, "humidity": 74}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 06:50:00',1795218600,'{"values": {"room": {"temperature": 27.0, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 07:00:00',1795219200,'{"values": {"room": {"temperature": 27.8, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 07:10:00',1795219800,'{"values": {"room": {"temperature": 27.2, "humidity": 70}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 07:20:00',1795220400,'{"values": {"room": {"temperature": 27.5, "humidity": 72}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 07:30:00',1795221000,'{"values": {"room": {"temperature": 27.8, "humidity": 70}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 07:40:00',1795221600,'{"values": {"room": {"temperature": 27.2, "humidity": 73}}, "errors": {}}'),
('esp32-a0b1c2d3e4f5','2026-11-21 07:50:00',1795222200,'{"values": {"room": {"temperature": 28.2, "humidity": 72}}, "errors": {}}');

INSERT INTO alert_rules (id,barn_id,metric,op,threshold,hold_samples,severity) VALUES
('3c0c0b4f-07cc-52e5-9a94-f2a819f9ea87','a3afb842-8624-57b8-89af-3a128de9a8a8','temperature','>',33,2,'warning');

INSERT INTO alerts (id,rule_id,device_id,severity,status,handled_by,note,raised_at,closed_at) VALUES
('e82bd6f4-ea4b-5a9a-8cd3-0279a0a2209f','3c0c0b4f-07cc-52e5-9a94-f2a819f9ea87','esp32-a0b1c2d3e4f5','warning','closed','626aebc4-ce24-5f00-8b89-ee91738fd249','Quạt đã bật tự động, mở thêm cửa thông gió','2026-11-20 13:10:00','2026-11-20 13:35:00'),
('29d44c68-27a5-54d8-b2cc-c85263d6bd0a',NULL,'esp32-a0b1c2d3e4f5','critical','acknowledged','626aebc4-ce24-5f00-8b89-ee91738fd249','Mất kết nối 3 phút do rút nguồn khi thử nghiệm','2026-11-21 04:00:00',NULL);

INSERT INTO commands (command_id,device_id,user_id,action,params,status,issued_at,acked_at) VALUES
('cmd-e177cb6d','esp32-a0b1c2d3e4f5','78d80cf1-09ee-5058-9659-b316e1dca476','feed','{}','success','2026-11-20 15:00:00','2026-11-20 15:00:01'),
('cmd-fb6433bf','esp32-a0b1c2d3e4f5','626aebc4-ce24-5f00-8b89-ee91738fd249','feed','{}','success','2026-11-20 19:00:00','2026-11-20 19:00:01'),
('cmd-a1989dde','esp32-a0b1c2d3e4f5','626aebc4-ce24-5f00-8b89-ee91738fd249','mode_set','{"mode": "MANUAL"}','success','2026-11-20 23:00:00','2026-11-20 23:00:01'),
('cmd-d1ded795','esp32-a0b1c2d3e4f5','626aebc4-ce24-5f00-8b89-ee91738fd249','relay_set','{"name": "fan", "on": true}','success','2026-11-20 23:01:00','2026-11-20 23:01:01'),
('cmd-6a5c89b7','esp32-a0b1c2d3e4f5','626aebc4-ce24-5f00-8b89-ee91738fd249','mode_set','{"mode": "AUTO"}','success','2026-11-20 23:10:00','2026-11-20 23:10:01'),
('cmd-35c6e8aa','esp32-a0b1c2d3e4f5','626aebc4-ce24-5f00-8b89-ee91738fd249','feed','{}','success','2026-11-21 01:00:00','2026-11-21 01:00:01');

INSERT INTO scheduled_events (id,barn_id,device_id,command_name,args,run_at,status,error,created_by,created_at,repeat_type,duration_seconds,executed_at) VALUES
('31118031-dd08-5e3e-ba55-fc934c820afc','a3afb842-8624-57b8-89af-3a128de9a8a8','esp32-a0b1c2d3e4f5','feed','{}','2026-11-21 07:00:00','pending',NULL,'626aebc4-ce24-5f00-8b89-ee91738fd249','2026-11-20 09:00:00','daily',10,NULL);

INSERT INTO device_events (device_id,type,detail,ts) VALUES
('esp32-a0b1c2d3e4f5','lifecycle','{"state": "online", "reason": "connect"}','2026-11-20 08:00:00'),
('esp32-a0b1c2d3e4f5','lifecycle','{"state": "offline", "reason": "lwt"}','2026-11-21 04:00:00'),
('esp32-a0b1c2d3e4f5','lifecycle','{"state": "online", "reason": "connect"}','2026-11-21 04:03:00');

INSERT INTO audit_logs (user_id,action,target,result,ts) VALUES
('78d80cf1-09ee-5058-9659-b316e1dca476','auth.login','users:78d80cf1-09ee-5058-9659-b316e1dca476','success','2026-11-20 09:00:00'),
('78d80cf1-09ee-5058-9659-b316e1dca476','registration.approve','registrations:a0b1c2d3e4f5','success','2026-11-20 10:00:00'),
('78d80cf1-09ee-5058-9659-b316e1dca476','device.barn.update','devices:esp32-a0b1c2d3e4f5','success','2026-11-20 11:00:00'),
('78d80cf1-09ee-5058-9659-b316e1dca476','alert_rule.create','alert_rules:3c0c0b4f-07cc-52e5-9a94-f2a819f9ea87','success','2026-11-20 12:00:00'),
('626aebc4-ce24-5f00-8b89-ee91738fd249','auth.login','users:626aebc4-ce24-5f00-8b89-ee91738fd249','success','2026-11-20 13:00:00'),
('626aebc4-ce24-5f00-8b89-ee91738fd249','scheduled_event.create','scheduled_events:31118031-dd08-5e3e-ba55-fc934c820afc','success','2026-11-20 14:00:00'),
('626aebc4-ce24-5f00-8b89-ee91738fd249','alert.acknowledge','alerts:e82bd6f4-ea4b-5a9a-8cd3-0279a0a2209f','success','2026-11-20 15:00:00'),
('626aebc4-ce24-5f00-8b89-ee91738fd249','alert.close','alerts:e82bd6f4-ea4b-5a9a-8cd3-0279a0a2209f','success','2026-11-20 16:00:00'),
('2559ee59-8017-551c-af1d-961d0b227ede','auth.login','users:2559ee59-8017-551c-af1d-961d0b227ede','success','2026-11-20 17:00:00');

SET FOREIGN_KEY_CHECKS=1;
