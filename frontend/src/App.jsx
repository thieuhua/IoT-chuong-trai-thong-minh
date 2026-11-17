import React, { useState, useEffect } from 'react';
import { useAuth } from './context/AuthContext';
import {
  apiGetHealth,
  apiGetBarns,
  apiGetDevices,
  apiGetRegistrations,
  apiGetAlerts,
} from './services/api';

import Navbar from './components/navigation/Navbar';
import Login from './components/auth/Login';
import PetCameraView from './components/camera/PetCameraView';
import BarnDashboard from './components/barn/BarnDashboard';
import DeviceManager from './components/devices/DeviceManager';
import AlertsCenter from './components/alerts/AlertsCenter';
import UserAdmin from './components/admin/UserAdmin';
import MobileAppView from './components/mobile/MobileAppView';

export default function App() {
  const { isAuthenticated, isAdmin } = useAuth();

  const [viewMode, setViewMode] = useState('desktop');
  const [activeTab, setActiveTab] = useState('camera');
  const [brokerOnline, setBrokerOnline] = useState(false);

  const [barns, setBarns] = useState([]);
  const [devices, setDevices] = useState([]);
  const [registrations, setRegistrations] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [notification, setNotification] = useState(null);

  const showNotification = (text, type = 'info') => {
    setNotification({ text, type });
    setTimeout(() => setNotification(null), 3000);
  };

  const syncSystemData = async () => {
    try {
      const health = await apiGetHealth();
      setBrokerOnline(Boolean(health.broker_connected));

      const [barnList, devList, regList, alertList] = await Promise.all([
        apiGetBarns().catch(() => []),
        apiGetDevices().catch(() => []),
        apiGetRegistrations('pending').catch(() => []),
        apiGetAlerts().catch(() => []),
      ]);

      setBarns(barnList);
      setDevices(devList);
      setRegistrations(regList);
      setAlerts(alertList);
    } catch {
      setBrokerOnline(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      syncSystemData();
      const timer = setInterval(syncSystemData, 4000);
      return () => clearInterval(timer);
    }
  }, [isAuthenticated]);

  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <div className="app-wrapper">
      <Navbar
        viewMode={viewMode}
        setViewMode={setViewMode}
        brokerOnline={brokerOnline}
      />

      {notification && (
        <div className={`toast-notification toast-${notification.type}`}>
          <span>{notification.text}</span>
          <button onClick={() => setNotification(null)} className="toast-close">
            ✕
          </button>
        </div>
      )}

      {viewMode === 'desktop' && (
        <>
          <nav className="tabs-nav">
            <button
              className={`tab-btn ${activeTab === 'camera' ? 'active' : ''}`}
              onClick={() => setActiveTab('camera')}
            >
              Camera AI
            </button>
            <button
              className={`tab-btn ${activeTab === 'sensors' ? 'active' : ''}`}
              onClick={() => setActiveTab('sensors')}
            >
              Môi Trường
            </button>
            <button
              className={`tab-btn ${activeTab === 'devices' ? 'active' : ''}`}
              onClick={() => setActiveTab('devices')}
            >
              Thiết Bị ({devices.length})
            </button>
            <button
              className={`tab-btn ${activeTab === 'alerts' ? 'active' : ''}`}
              onClick={() => setActiveTab('alerts')}
            >
              Cảnh Báo
              {alerts.filter((a) => a.status === 'open' || a.status === 'active').length > 0 && (
                <span className="badge-count">
                  {alerts.filter((a) => a.status === 'open' || a.status === 'active').length}
                </span>
              )}
            </button>
            {isAdmin && (
              <button
                className={`tab-btn ${activeTab === 'admin' ? 'active' : ''}`}
                onClick={() => setActiveTab('admin')}
              >
                Hệ Thống
              </button>
            )}
          </nav>

          <main className="tab-content">
            {activeTab === 'camera' && (
              <PetCameraView devices={devices} onNotify={showNotification} />
            )}
            {activeTab === 'sensors' && (
              <BarnDashboard barns={barns} devices={devices} onNotify={showNotification} />
            )}
            {activeTab === 'devices' && (
              <DeviceManager
                barns={barns}
                devices={devices}
                registrations={registrations}
                onRefreshDevices={syncSystemData}
                onRefreshRegistrations={syncSystemData}
                onNotify={showNotification}
              />
            )}
            {activeTab === 'alerts' && (
              <AlertsCenter
                alerts={alerts}
                onRefreshAlerts={syncSystemData}
                onNotify={showNotification}
              />
            )}
            {activeTab === 'admin' && isAdmin && (
              <UserAdmin onNotify={showNotification} />
            )}
          </main>
        </>
      )}

      {viewMode === 'mobile' && (
        <MobileAppView
          devices={devices}
          alerts={alerts}
          onNotify={showNotification}
        />
      )}
    </div>
  );
}
