```tsx
/* eslint-disable react-hooks/exhaustive-deps */

/*
 |------------------------------------------------------------------
 | GovernancePage.tsx
 |------------------------------------------------------------------
 |
 | Front-end page that lets fans stake their Show-Pass NFTs and
 | participate in on-chain DAO governance.  Consumes the domain
 | layer exclusively through application-service ports exposed by
 | the GovernanceService adapter.  Real-time proposal updates are
 | streamed over a GraphQL subscription so that vote tallies are
 | reflected instantly without a browser refresh.
 |
 | The component purposefully contains zero business logic—
 | everything is delegated to the injected service.  That keeps
 | the React layer thin and compliant with the project’s Clean
 | Architecture guidelines.
 |
 */

import React, {
  FC,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Snackbar,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import { formatDistanceToNow } from 'date-fns';
import { gql, useMutation, useQuery, useSubscription } from '@apollo/client';
import BigNumber from 'bignumber.js';

import { useWallet } from '../hooks/useWallet';
import { GovernanceService } from '../services/GovernanceService';
import { Pass } from '../../domain/entities/Pass';
import { Proposal } from '../../domain/entities/Proposal';

/* ------------------------------------------------------------------ */
/* GraphQL documents                                                   */
/* ------------------------------------------------------------------ */

const GET_USER_PASSES = gql`
  query GetUserPasses($owner: String!) {
    passes(owner: $owner) {
      id
      showId
      staked
      level
      image
    }
  }
`;

const GET_PROPOSALS = gql`
  query GetProposals {
    proposals {
      id
      title
      description
      startsAt
      endsAt
      forVotes
      againstVotes
      state
    }
  }
`;

const PROPOSAL_SUBSCRIPTION = gql`
  subscription OnProposalUpdated {
    proposalUpdated {
      id
      forVotes
      againstVotes
      state
    }
  }
`;

const CAST_VOTE = gql`
  mutation CastVote($proposalId: ID!, $support: Boolean!, $weight: String!) {
    castVote(proposalId: $proposalId, support: $support, weight: $weight) {
      id
      forVotes
      againstVotes
      state
    }
  }
`;

const STAKE_PASS = gql`
  mutation StakePass($passId: ID!) {
    stakePass(passId: $passId) {
      id
      staked
    }
  }
`;

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

const GovernancePage: FC = () => {
  /* ---------------------------- dependencies ---------------------------- */

  const wallet = useWallet(); // abstracted wallet (MetaMask / WalletConnect / etc.)
  const governance = useMemo(() => new GovernanceService(), []);

  /* ------------------------------- query ------------------------------- */

  const {
    data: passesData,
    loading: passesLoading,
    refetch: refetchPasses,
  } = useQuery<{ passes: Pass[] }>(GET_USER_PASSES, {
    variables: { owner: wallet.account ?? '' },
    skip: !wallet.account,
    fetchPolicy: 'cache-and-network',
  });

  const {
    data: proposalsData,
    loading: proposalsLoading,
    subscribeToMore,
  } = useQuery<{ proposals: Proposal[] }>(GET_PROPOSALS, {
    fetchPolicy: 'cache-and-network',
  });

  /* -------------------------- live subscription ------------------------- */

  useEffect(() => {
    if (!subscribeToMore) return;

    const unsubscribe = subscribeToMore<{ proposalUpdated: Proposal }>({
      document: PROPOSAL_SUBSCRIPTION,
      updateQuery: (prev, { subscriptionData }) => {
        if (!subscriptionData.data) return prev;
        const updated = subscriptionData.data.proposalUpdated;

        return {
          proposals: prev.proposals.map((p) =>
            p.id === updated.id ? { ...p, ...updated } : p,
          ),
        };
      },
    });

    return () => {
      unsubscribe();
    };
  }, [subscribeToMore]);

  /* ---------------------------- mutations ------------------------------ */

  const [castVoteMutation] = useMutation(CAST_VOTE);
  const [stakePassMutation] = useMutation(STAKE_PASS);

  /* ------------------------------ state -------------------------------- */

  const [tab, setTab] = useState<'proposals' | 'stake'>('proposals');
  const [snackbar, setSnackbar] = useState<{
    open: boolean;
    message?: string;
    severity?: 'success' | 'error';
  }>({ open: false });

  /* -------------------------------------------------------------------- */
  /* Callbacks                                                            */
  /* -------------------------------------------------------------------- */

  const handleTabChange = (_: unknown, newValue: typeof tab) => {
    setTab(newValue);
  };

  const handleStake = useCallback(
    async (passId: string) => {
      try {
        await stakePassMutation({ variables: { passId } });
        setSnackbar({
          open: true,
          message: 'Pass staked successfully!',
          severity: 'success',
        });
        refetchPasses();
      } catch (err) {
        console.error(err);
        setSnackbar({
          open: true,
          message: (err as Error).message,
          severity: 'error',
        });
      }
    },
    [stakePassMutation, refetchPasses],
  );

  const handleVote = useCallback(
    async ({
      proposalId,
      support,
    }: {
      proposalId: string;
      support: boolean;
    }) => {
      try {
        if (!wallet.account) throw new Error('Connect your wallet first');

        const weight = await governance.getVotingPower(wallet.account); // BNish
        await castVoteMutation({
          variables: {
            proposalId,
            support,
            weight: weight.toString(10),
          },
        });

        setSnackbar({
          open: true,
          message: 'Vote cast successfully!',
          severity: 'success',
        });
      } catch (err) {
        console.error(err);
        setSnackbar({
          open: true,
          message: (err as Error).message,
          severity: 'error',
        });
      }
    },
    [castVoteMutation, wallet.account, governance],
  );

  /* ----------------------------- helpers ------------------------------- */

  const stakablePasses = useMemo(
    () =>
      (passesData?.passes ?? []).filter((p) => !p.staked) as Pass[],
    [passesData],
  );

  const proposals = useMemo(
    () => proposalsData?.proposals ?? [],
    [proposalsData],
  );

  /* -------------------------------------------------------------------- */
  /* Render helpers                                                       */
  /* -------------------------------------------------------------------- */

  const renderStakeTab = () => (
    <Box display="flex" flexWrap="wrap" gap={3}>
      {passesLoading && (
        <Box width="100%" display="flex" justifyContent="center" py={4}>
          <CircularProgress />
        </Box>
      )}
      {!passesLoading && stakablePasses.length === 0 && (
        <Typography>You have no unstaked passes.</Typography>
      )}

      {stakablePasses.map((pass) => (
        <Card key={pass.id} sx={{ width: 250 }}>
          <CardContent>
            <img
              src={pass.image}
              alt={`Pass ${pass.id}`}
              style={{ width: '100%', borderRadius: 8 }}
            />

            <Typography variant="h6" mt={1}>
              Show #{pass.showId}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Level {pass.level}
            </Typography>

            <Button
              fullWidth
              variant="contained"
              sx={{ mt: 2 }}
              onClick={() => handleStake(pass.id)}
            >
              Stake Pass
            </Button>
          </CardContent>
        </Card>
      ))}
    </Box>
  );

  const renderProposalsTab = () => (
    <Box display="flex" flexDirection="column" gap={3}>
      {proposalsLoading && (
        <Box width="100%" display="flex" justifyContent="center" py={4}>
          <CircularProgress />
        </Box>
      )}
      {!proposalsLoading && proposals.length === 0 && (
        <Typography>No active proposals.</Typography>
      )}

      {proposals.map((proposal) => {
        const endsIn = formatDistanceToNow(new Date(proposal.endsAt), {
          addSuffix: true,
        });
        const totalVotes = new BigNumber(proposal.forVotes).plus(
          proposal.againstVotes,
        );
        const forPercent = totalVotes.isZero()
          ? 0
          : new BigNumber(proposal.forVotes)
              .dividedBy(totalVotes)
              .multipliedBy(100)
              .toNumber();

        return (
          <Card key={proposal.id}>
            <CardContent>
              <Typography variant="h6">{proposal.title}</Typography>
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                {proposal.description}
              </Typography>

              <Typography variant="caption" color="text.secondary">
                Ends {endsIn}
              </Typography>

              <Box display="flex" gap={1} mt={2}>
                <Button
                  variant="outlined"
                  onClick={() => handleVote({ proposalId: proposal.id, support: true })}
                  disabled={proposal.state !== 'Active'}
                >
                  For
                </Button>
                <Button
                  variant="outlined"
                  color="error"
                  onClick={() =>
                    handleVote({ proposalId: proposal.id, support: false })
                  }
                  disabled={proposal.state !== 'Active'}
                >
                  Against
                </Button>
              </Box>

              <Box display="flex" gap={2} mt={2}>
                <Typography variant="caption">
                  For: {forPercent.toFixed(1)}%
                </Typography>
                <Typography variant="caption">
                  Total votes: {totalVotes.toFormat(0)}
                </Typography>
              </Box>
            </CardContent>
          </Card>
        );
      })}
    </Box>
  );

  /* -------------------------------------------------------------------- */
  /* JSX                                                                  */
  /* -------------------------------------------------------------------- */

  return (
    <Box p={4}>
      <Typography variant="h4" mb={3}>
        DAO Governance
      </Typography>

      <Tabs value={tab} onChange={handleTabChange} sx={{ mb: 4 }}>
        <Tab label="Proposals" value="proposals" />
        <Tab label="Stake Pass" value="stake" />
      </Tabs>

      {tab === 'proposals' ? renderProposalsTab() : renderStakeTab()}

      {/* Snackbar for flash messages */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        message={snackbar.message}
      />
    </Box>
  );
};

export default GovernancePage;
```