import { useState, type FormEvent } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import axios from 'axios';

import { login } from '../api/auth';
import { useAuthStore } from '../store/auth';

/**
 * Login screen.
 *
 * Posts credentials via `login()` (OAuth2 password flow); on success the auth
 * store is populated and the optional `onSuccess` callback fires so a human can
 * redirect/route after wiring this into the router. Self-contained: does not
 * touch App.tsx or Layout.tsx.
 */
export function LoginPage({ onSuccess }: { onSuccess?: () => void }) {
  const user = useAuthStore((s) => s.user);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      onSuccess?.();
    } catch (err: unknown) {
      let message = 'Login failed. Please try again.';
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 401) {
          message = 'Invalid username or password.';
        } else if (typeof err.response?.data?.detail === 'string') {
          message = err.response.data.detail;
        } else if (!err.response) {
          message = 'Could not reach the server.';
        }
      }
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  if (user) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <Alert severity="success">
          Signed in as <strong>{user.username}</strong>.
        </Alert>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '60vh',
        p: 2,
      }}
    >
      <Card variant="outlined" sx={{ width: '100%', maxWidth: 380 }}>
        <CardContent>
          <Typography variant="h5" gutterBottom>
            Sign in
          </Typography>
          <Box component="form" onSubmit={handleSubmit} noValidate>
            <Stack spacing={2}>
              {error && <Alert severity="error">{error}</Alert>}
              <TextField
                label="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                fullWidth
                autoComplete="username"
                disabled={submitting}
              />
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                fullWidth
                autoComplete="current-password"
                disabled={submitting}
              />
              <Button
                type="submit"
                variant="contained"
                disabled={submitting || !username.trim() || !password}
                startIcon={
                  submitting ? <CircularProgress size={18} /> : undefined
                }
              >
                Sign in
              </Button>
            </Stack>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
