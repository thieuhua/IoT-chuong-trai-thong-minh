import React, { useState, useEffect, useRef } from 'react';
import {
  apiGetCameraStatus,
  apiStartCamera,
  apiStopCamera,
} from '../../services/api';
import LiveVideoPlayer from './LiveVideoPlayer';
import PetActivityLog from './PetActivityLog';

export default function PetCameraView({ onNotify }) {
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

  return (
    <div className="dashboard-grid">
      {/* Cột trái: Luồng Video */}
      <div>
        <LiveVideoPlayer
          cameraStatus={cameraStatus}
          onToggleCamera={toggleCamera}
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
