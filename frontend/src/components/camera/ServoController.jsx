import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';

export default function ServoController({
  devices,
  onFeed,
}) {
  const { canControl } = useAuth();
  const [servoAngle, setServoAngle] = useState(90);
  const [isFeeding, setIsFeeding] = useState(false);

  const handleFeedClick = async () => {
    setIsFeeding(true);
    try {
      await onFeed(Number(servoAngle));
    } finally {
      setIsFeeding(false);
    }
  };

  return (
    <div className="card">
      <h3 className="card-title">Máng Ăn Tự Động</h3>
      <div className="actuator-controls">
        <div className="input-inline">
          <label>Góc mở:</label>
          <input
            type="number"
            min="0"
            max="180"
            value={servoAngle}
            onChange={(e) => setServoAngle(e.target.value)}
            className="input-number"
          />
          <span>độ</span>
        </div>
        <button
          className="btn btn-success"
          onClick={handleFeedClick}
          disabled={isFeeding || !canControl || !devices || devices.length === 0}
        >
          {isFeeding ? 'Đang mở...' : 'Cho Ăn'}
        </button>
      </div>
    </div>
  );
}
