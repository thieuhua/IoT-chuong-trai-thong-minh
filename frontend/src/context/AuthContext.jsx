import React, { createContext, useContext, useState, useEffect } from 'react';
import {
  getStoredUser,
  getStoredToken,
  apiLogin,
  apiLogout,
  clearSession,
} from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => getStoredUser());
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(getStoredToken() && getStoredUser()));
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const handleAuthExpired = () => {
      setUser(null);
      setIsAuthenticated(false);
    };
    window.addEventListener('auth:expired', handleAuthExpired);
    return () => window.removeEventListener('auth:expired', handleAuthExpired);
  }, []);

  const login = async (username, password) => {
    setLoading(true);
    try {
      const data = await apiLogin(username, password);
      setUser(data.user);
      setIsAuthenticated(true);
      return data.user;
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await apiLogout();
    } finally {
      clearSession();
      setUser(null);
      setIsAuthenticated(false);
    }
  };

  const value = {
    user,
    isAuthenticated,
    loading,
    login,
    logout,
    isAdmin: user?.role === 'Admin',
    isOperator: user?.role === 'Operator',
    isViewer: user?.role === 'Viewer',
    canControl: user?.role === 'Admin' || user?.role === 'Operator',
    canManage: user?.role === 'Admin',
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
