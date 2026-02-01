```tsx
/* eslint-disable react-hooks/exhaustive-deps */
import React, { useCallback, useMemo, useState } from 'react';
import { gql, useMutation, useSubscription } from '@apollo/client';
import {
  Box,
  Button,
  CircularProgress,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { toast } from 'react-toastify';

/**
 * -------------------------------------------------------------
 *  LivePoll.tsx
 *  StellarStage Carnival – Front-End
 * -------------------------------------------------------------
 *  UI component that renders the currently-active, real-time poll
 *  for a given show. Poll data is streamed via GraphQL
 *  subscriptions coming from the event-driven backend.
 *
 *  When a user picks an option, we optimistically update the UI
 *  and invoke the “CastLiveVote” use-case through a GraphQL
 *  mutation. All blockchain specifics (signing, gas, tx status)
 *  are abstracted behind the corresponding backend adapter.
 * -------------------------------------------------------------
 */

/* ------------  GraphQL documents  ----------- */

const LIVE_POLL_SUBSCRIPTION = gql`
  subscription LivePoll($showId: ID!) {
    livePoll(showId: $showId) {
      id
      question
      closesAt
      userVoteOptionId      # null until current wallet has voted
      options {
        id
        label
        votes                # back-end keeps this lightweight
      }
    }
  }
`;

const CAST_VOTE_MUTATION = gql`
  mutation CastVote($input: CastVoteInput!) {
    castVote(input: $input) {
      success
      message
    }
  }
`;

/* ------------  Types  ----------- */

export interface LivePollProps {
  /** Unique show identifier (contract address or UUID)  */
  showId: string;
  /**
   * The currently connected wallet address.
   * Used to guarantee one vote per wallet.
   */
  walletAddress: string;
}

/* ------------  Helper utils  ----------- */

/**
 * Calculates each option’s percentage while gracefully
 * handling the “division by zero” scenario.
 */
function computePercent(votes: number, total: number): number {
  if (total === 0) return 0;
  return Number(((votes / total) * 100).toFixed(1));
}

/* ------------  Component  ----------- */

const LivePoll: React.FC<LivePollProps> = ({ showId, walletAddress }) => {
  /* ----------  State & apollo  ---------- */

  const { data, loading, error } = useSubscription<{
    livePoll: {
      id: string;
      question: string;
      closesAt: string; // ISO date
      userVoteOptionId: string | null;
      options: { id: string; label: string; votes: number }[];
    };
  }>(LIVE_POLL_SUBSCRIPTION, {
    variables: { showId },
    shouldResubscribe: true,
  });

  const [castVote, { loading: voting }] = useMutation(CAST_VOTE_MUTATION);

  /* ----------  Derived memo values  ---------- */

  const poll = data?.livePoll;

  const totalVotes = useMemo(
    () => poll?.options.reduce((acc, o) => acc + o.votes, 0) ?? 0,
    [poll?.options]
  );

  const isPollClosed = useMemo(() => {
    if (!poll?.closesAt) return false;
    return new Date(poll.closesAt).getTime() <= Date.now();
  }, [poll?.closesAt]);

  /* ----------  Event handlers  ---------- */

  const handleVote = useCallback(
    async (optionId: string) => {
      if (!poll || isPollClosed) return;

      try {
        await castVote({
          variables: {
            input: {
              pollId: poll.id,
              optionId,
              voter: walletAddress,
            },
          },
          /* Optimistic response for snappy UI */
          optimisticResponse: {
            castVote: {
              __typename: 'CastVotePayload',
              success: true,
              message: 'Vote submitted',
            },
          },
          /* Let Apollo merge the new vote count; here we simply
           * add “1” to the selected option in the cache.
           */
          update: (cache) => {
            const pollId = cache.identify({ __typename: 'LivePoll', id: poll.id });
            cache.modify({
              id: pollId,
              fields: {
                userVoteOptionId() {
                  return optionId;
                },
                options(existingOptions: any[]) {
                  return existingOptions.map((opt) =>
                    opt.id === optionId
                      ? {
                          ...opt,
                          votes: opt.votes + 1,
                        }
                      : opt
                  );
                },
              },
            });
          },
        });

        toast.success('Your vote was broadcast 🚀');
      } catch (e: any) {
        console.error('[LivePoll] castVote failed', e);
        toast.error(
          e?.message ?? 'Something went wrong while submitting your vote.'
        );
      }
    },
    [castVote, poll, walletAddress, isPollClosed]
  );

  /* ----------  Render helpers  ---------- */

  if (loading) {
    return (
      <Box display="flex" alignItems="center" justifyContent="center" py={4}>
        <CircularProgress size={32} />
      </Box>
    );
  }

  if (error || !poll) {
    return (
      <Typography color="error">
        Unable to load live poll. Please try again later.
      </Typography>
    );
  }

  return (
    <Paper elevation={3} sx={{ p: 3 }}>
      <Stack spacing={2}>
        {/* Question / Close info */}
        <Typography variant="h6" fontWeight={600}>
          {poll.question}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {isPollClosed
            ? 'Poll closed'
            : `Poll closes at ${new Date(
                poll.closesAt
              ).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
        </Typography>

        {/* Options */}
        {poll.options.map((opt) => {
          const percent = computePercent(opt.votes, totalVotes);
          const userHasVoted = !!poll.userVoteOptionId;
          const isMyVote = poll.userVoteOptionId === opt.id;

          return (
            <Box key={opt.id}>
              <Stack direction="row" alignItems="center" spacing={1}>
                <Button
                  variant={isMyVote ? 'contained' : 'outlined'}
                  color={isMyVote ? 'primary' : 'inherit'}
                  disabled={userHasVoted || isPollClosed || voting}
                  onClick={() => handleVote(opt.id)}
                  sx={{ minWidth: 120 }}
                >
                  {isMyVote ? 'Your Vote' : 'Vote'}
                </Button>
                <Typography variant="body1" sx={{ flexGrow: 1 }}>
                  {opt.label}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{ width: 50, textAlign: 'right' }}
                >
                  {percent}%
                </Typography>
              </Stack>

              {/* Progress bar */}
              <LinearProgress
                variant="determinate"
                value={percent}
                sx={{
                  height: 6,
                  borderRadius: 2,
                  mt: 1,
                  bgcolor: 'grey.200',
                  '& .MuiLinearProgress-bar': {
                    backgroundColor: isMyVote ? 'primary.main' : 'secondary.main',
                  },
                }}
              />
            </Box>
          );
        })}

        {/* Footer stats */}
        <Typography
          variant="caption"
          color="text.secondary"
          alignSelf="flex-end"
        >
          {totalVotes.toLocaleString()} vote{totalVotes !== 1 ? 's' : ''}
        </Typography>
      </Stack>
    </Paper>
  );
};

export default LivePoll;
```
