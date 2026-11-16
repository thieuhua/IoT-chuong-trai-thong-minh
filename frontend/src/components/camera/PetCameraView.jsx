import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiGetCameraStatus,
  apiStartCamera,
  apiStopCamera,
  apiSendDeviceCommand,
} from '../../services/api';
import LiveVideoPlayer from './LiveVideoPlayer';
import ServoController from './ServoController';
import PetActivityLog from './PetActivityLog';

export default function PetCameraView({ devices, onNotify }) {
  const { canControl } = useAuth();
  const [cameraStatus, setCameraStatus] = useState({
    is_running: false,
    state: 'absent',
    label: 'Chưa kích hoạt',
    duration_s: 0,
    speed_px_s: 0,
    still_duration_s: 0,
    fps: 0,
  });

  const [petLogs, setPetLogs] = useState([]);
  const prevPetState = useRef(null);

  // Đồng bộ trạng thái Camera AI
  useEffect(() => {
    let isMounted = true;
    const fetchStatus = async () => {
      try {
        const res = await apiGetCameraStatus();
        if (isMounted && res.is_available) {
          setCameraStatus((prev) => ({ ...prev, ...res }));

          if (res.is_running && res.state && res.state !== prevPetState.current) {
            setPetLogs((prev) => [
              {
                id: Date.now(),
                time: new Date().toLocaleTimeString(),
                state: res.state,
                label: res.label,
              },
              ...prev,
            ]);
            prevPetState.current = res.state;
          }
        }
      } catch {
        // Camera server chưa bật
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 1500);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const toggleCamera = async () => {
    try {
      if (cameraStatus.is_running) {
        await apiStopCamera();
        setCameraStatus((prev) => ({ ...prev, is_running: false, label: 'Đã tắt' }));
        onNotify('Đã tắt Camera AI.');
      } else {
        await apiStartCamera();
        setCameraStatus((prev) => ({ ...prev, is_running: true, label: 'Đang khởi động...' }));
        onNotify('Đã bật Camera AI.');
      }
    } catch (err) {
      onNotify('Lỗi điều khiển camera: ' + err.message, 'error');
    }
  };

  const handleFeed = async (servoAngle) => {
    if (!canControl) {
      onNotify('Tài khoản Người xem không có quyền điều khiển thiết bị.', 'error');
      return;
    }

    if (!devices || devices.length === 0) {
      onNotify('Không tìm thấy thiết bị ESP32 trong chuồng để nhận lệnh.', 'error');
      return;
    }

    const targetDevice = devices[0].device_id;
    try {
      await apiSendDeviceCommand(targetDevice, 'servo_set', { angle: servoAngle });
      onNotify(`Đã mở máng ăn (${servoAngle}°) tới ${targetDevice}`);
    } catch (err) {
      onNotify('Lỗi gửi lệnh máng ăn: ' + err.message, 'error');
    }
  };

  return (
    <div className="dashboard-grid">
      {/* Cột trái: Luồng Video và Điều khiển Máng Ăn */}
      <div>
        <LiveVideoPlayer
          cameraStatus={cameraStatus}
          onToggleCamera={toggleCamera}
        />
        <ServoController
          devices={devices}
          onFeed={handleFeed}
        />
      </div>

      {/* Cột phải: Nhật ký hoạt động */}
      <div>
        <PetActivityLog
          petLogs={petLogs}
          isRunning={cameraStatus.is_running}
          onClear={() => setPetLogs([])}
        />
      </div>
    </div>
  );
}
