```tsx
/**
 * StakingDashboard
 * -----------------------------------------------------------------------------
 * A rich UI component that lets the fan stake / unstake their Show-Pass NFTs to
 * earn governance rights over future line-ups.  All business logic lives in the
 * domain + use-case layers; this UI merely invokes the corresponding adapters
 * through strongly-typed hooks.
 *
 * Clean-architecture boundaries are preserved – the dashboard never touches web3
 * providers, smart-contract ABIs or GraphQL documents directly.
 */

import React, {
  useCallback,
  useMemo,
  useState,
  SyntheticEvent,
  Fragment,
} from 'react';
import {
  Box,
  Card,
  CardActions,
  CardContent,
  CardMedia,
  CircularProgress,
  Divider,
  Grid,
  Snackbar,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material';
import MuiAlert, { AlertProps } from '@mui/material/Alert';
import StakeIcon from '@mui/icons-material/LocalOfferOutlined';
import UnstakeIcon from '@mui/icons-material/UnpublishedOutlined';
import GovernanceIcon from '@mui/icons-material/HowToVoteOutlined';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { formatDistanceToNowStrict } from 'date-fns';

import {
  PassSummary,
  StakingPosition,
} from '../../domain/entities/pass.types';
import { WalletAddress } from '../../domain/value-objects/wallet.types';

import {
  queryUnstakedPasses,
  queryStakingPositions,
  stakePass,
  unstakePass,
} from '../../services/stakingService';
import { useWallet } from '../../hooks/useWallet';

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(function Alert(
  props,
  ref,
) {
  return <MuiAlert elevation={6} ref={ref} variant="filled" {...props} />;
});

const formatCountdown = (unlockTs: number): string =>
  unlockTs === 0
    ? 'Unlocked'
    : `${formatDistanceToNowStrict(unlockTs * 1000, { addSuffix: true })}`;

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

const TAB = {
  STAKE: 0,
  POSITIONS: 1,
} as const;

export const StakingDashboard: React.FC = () => {
  /* ─────────────────────────────────────────────────────────────────── State */
  const { address } = useWallet() as { address: WalletAddress | null };
  const [activeTab, setActiveTab] = useState<number>(TAB.POSITIONS);
  const [snack, setSnack] = useState<{
    open: boolean;
    message: string;
    severity: AlertProps['severity'];
  }>({ open: false, message: '', severity: 'success' });

  const queryClient = useQueryClient();

  /* ─────────────────────────────────────────────────────────────────── Data */

  const {
    data: stakingPositions,
    isLoading: loadingPositions,
    error: positionsError,
  } = useQuery<StakingPosition[]>(
    ['stakingPositions', address],
    () => queryStakingPositions(address!),
    {
      enabled: Boolean(address),
      staleTime: 20_000,
    },
  );

  const {
    data: availablePasses,
    isLoading: loadingPasses,
    error: passesError,
  } = useQuery<PassSummary[]>(
    ['unstakedPasses', address],
    () => queryUnstakedPasses(address!),
    {
      enabled: Boolean(address),
      staleTime: 20_000,
    },
  );

  /* ─────────────────────────────────────────────────────────────── Mutations */

  const { mutate: doStake, isLoading: staking } = useMutation(stakePass, {
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries(['unstakedPasses', address]),
        queryClient.invalidateQueries(['stakingPositions', address]),
      ]);
      setSnack({
        open: true,
        message: 'Pass successfully staked!',
        severity: 'success',
      });
    },
    onError: (e: unknown) =>
      setSnack({
        open: true,
        message: (e as Error).message || 'Failed to stake. Try again.',
        severity: 'error',
      }),
  });

  const { mutate: doUnstake, isLoading: unstaking } = useMutation(unstakePass, {
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries(['unstakedPasses', address]),
        queryClient.invalidateQueries(['stakingPositions', address]),
      ]);
      setSnack({
        open: true,
        message: 'Pass successfully unstaked!',
        severity: 'success',
      });
    },
    onError: (e: unknown) =>
      setSnack({
        open: true,
        message: (e as Error).message || 'Failed to unstake.  Try again.',
        severity: 'error',
      }),
  });

  /* ───────────────────────────────────────────────────────────── Handlers */

  const handleTabChange = (_: SyntheticEvent, value: number) =>
    setActiveTab(value);

  const handleStake = useCallback(
    (passId: string) => {
      if (!address) return;
      doStake({ passId, owner: address });
    },
    [doStake, address],
  );

  const handleUnstake = useCallback(
    (positionId: string) => {
      if (!address) return;
      doUnstake({ positionId, owner: address });
    },
    [doUnstake, address],
  );

  const handleSnackClose = () => setSnack((s) => ({ ...s, open: false }));

  /* ───────────────────────────────────────────────────────────── Derivatives */

  const isLoading = useMemo(
    () => loadingPasses || loadingPositions || staking || unstaking,
    [loadingPasses, loadingPositions, staking, unstaking],
  );

  /* ─────────────────────────────────────────────────────────── UI Renderers */

  const renderPassCard = (pass: PassSummary) => (
    <Card key={pass.id} variant="outlined" sx={{ height: '100%' }}>
      <CardMedia
        component="img"
        height={180}
        image={pass.thumbnailUrl}
        alt={pass.title}
      />
      <CardContent>
        <Typography variant="h6" gutterBottom noWrap>
          {pass.title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Rarity&nbsp;&middot;&nbsp;
          {pass.rarity}
        </Typography>
      </CardContent>
      <Divider />
      <CardActions>
        <Tooltip title="Stake this pass to start earning governance power">
          <Box sx={{ ml: 'auto' }}>
            <StakeIcon fontSize="small" color="primary" />
            <Box
              component="span"
              sx={{ ml: 1, cursor: 'pointer', fontWeight: 600 }}
              onClick={() => handleStake(pass.id)}
            >
              Stake
            </Box>
          </Box>
        </Tooltip>
      </CardActions>
    </Card>
  );

  const renderPositionCard = (pos: StakingPosition) => {
    const unlockCountdown = formatCountdown(pos.unlockAt);
    return (
      <Card key={pos.positionId} variant="outlined" sx={{ height: '100%' }}>
        <CardMedia
          component="img"
          height={180}
          image={pos.pass.thumbnailUrl}
          alt={pos.pass.title}
        />
        <CardContent>
          <Typography variant="h6" gutterBottom noWrap>
            {pos.pass.title}
          </Typography>

          <Grid container spacing={1}>
            <Grid item xs={12} sm={6}>
              <Box display="flex" alignItems="center">
                <GovernanceIcon fontSize="small" sx={{ mr: 0.5 }} />
                <Typography variant="body2" color="text.secondary">
                  GP&nbsp;Earned:&nbsp;{pos.governancePower}
                </Typography>
              </Box>
            </Grid>

            <Grid item xs={12} sm={6}>
              <Typography variant="body2" color="text.secondary">
                Unlocks&nbsp;{unlockCountdown}
              </Typography>
            </Grid>
          </Grid>
        </CardContent>
        <Divider />
        <CardActions>
          <Tooltip
            title={
              pos.unlockAt * 1000 > Date.now()
                ? 'Cannot unstake until lock-up expires'
                : 'Withdraw your pass'
            }
          >
            <Box sx={{ ml: 'auto' }}>
              <UnstakeIcon
                fontSize="small"
                color={
                  pos.unlockAt * 1000 > Date.now() ? 'disabled' : 'action'
                }
              />
              <Box
                component="span"
                sx={{
                  ml: 1,
                  cursor:
                    pos.unlockAt * 1000 > Date.now() ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  color:
                    pos.unlockAt * 1000 > Date.now()
                      ? 'text.disabled'
                      : 'text.primary',
                }}
                onClick={() =>
                  pos.unlockAt * 1000 <= Date.now() &&
                  handleUnstake(pos.positionId)
                }
              >
                Unstake
              </Box>
            </Box>
          </Tooltip>
        </CardActions>
      </Card>
    );
  };

  /* ─────────────────────────────────────────────────────────────── Render */

  return (
    <Fragment>
      <Box mb={3}>
        <Typography variant="h4">Staking Dashboard</Typography>
        <Typography variant="body1" color="text.secondary">
          Stake your Show-Pass NFTs to earn governance power and shape the next
          line-ups
        </Typography>
      </Box>

      <Tabs
        value={activeTab}
        onChange={handleTabChange}
        aria-label="staking tabs"
        sx={{ mb: 3 }}
      >
        <Tab label="My Positions" id="tab-positions" />
        <Tab label="Stake New Pass" id="tab-stake" />
      </Tabs>

      {isLoading && (
        <Box textAlign="center" mt={6}>
          <CircularProgress />
        </Box>
      )}

      {!isLoading && activeTab === TAB.STAKE && (
        <Grid container spacing={3}>
          {availablePasses?.length ? (
            availablePasses.map(renderPassCard)
          ) : (
            <Grid item xs={12}>
              <Typography color="text.secondary">
                No unstaked passes found in your wallet.
              </Typography>
            </Grid>
          )}
        </Grid>
      )}

      {!isLoading && activeTab === TAB.POSITIONS && (
        <Grid container spacing={3}>
          {stakingPositions?.length ? (
            stakingPositions.map(renderPositionCard)
          ) : (
            <Grid item xs={12}>
              <Typography color="text.secondary">
                You haven’t staked any passes yet.
              </Typography>
            </Grid>
          )}
        </Grid>
      )}

      {/* Global feedback snackbar */}
      <Snackbar
        open={snack.open}
        autoHideDuration={6000}
        onClose={handleSnackClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={handleSnackClose}
          severity={snack.severity}
          sx={{ width: '100%' }}
        >
          {snack.message}
        </Alert>
      </Snackbar>

      {/* Error boundaries (high-level) */}
      {(positionsError || passesError) && (
        <Box mt={4}>
          <Alert severity="error">
            {positionsError?.toString() || passesError?.toString()}
          </Alert>
        </Box>
      )}
    </Fragment>
  );
};

export default StakingDashboard;
```
