```tsx
/* eslint-disable react-hooks/exhaustive-deps */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  CircularProgress,
  Flex,
  Heading,
  HStack,
  IconButton,
  Modal,
  ModalBody,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Progress,
  Text,
  Tooltip,
  useDisclosure,
  useToast,
  VStack,
} from '@chakra-ui/react';
import { TriangleDownIcon } from '@chakra-ui/icons';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useParams } from 'react-router-dom';
import {
  ApolloError,
  gql,
  useMutation,
  useQuery,
  useSubscription,
} from '@apollo/client';

/**
 * ===========================================================================
 *  GraphQL docs
 * ===========================================================================
 */
const SHOW_DETAILS_QUERY = gql`
  query ShowDetails($id: ID!) {
    show(id: $id) {
      id
      title
      description
      coverImage
      startTime
      totalPassSupply
      mintedPassCount
      acts {
        id
        name
        order
        duration
      }
      userPass {
        id
        level
        stakedBalance
        hasVoted
      }
    }
  }
`;

const SHOW_EVENTS_SUBSCRIPTION = gql`
  subscription OnShowEvent($showId: ID!) {
    showEvent(showId: $showId) {
      __typename
      ... on ActStartedEvent {
        actId
        timestamp
      }
      ... on LootDropEvent {
        lootId
        rarity
        timestamp
      }
      ... on VoteWindowOpenedEvent {
        proposalId
        choices
        endsAt
      }
    }
  }
`;

const MINT_PASS_MUTATION = gql`
  mutation MintShowPass($showId: ID!) {
    mintPass(showId: $showId) {
      id
      level
      txHash
    }
  }
`;

const STAKE_PASS_MUTATION = gql`
  mutation StakePass($passId: ID!) {
    stakePass(passId: $passId) {
      stakedBalance
      txHash
    }
  }
`;

const CAST_VOTE_MUTATION = gql`
  mutation CastVote($proposalId: ID!, $choice: String!) {
    castLiveVote(proposalId: $proposalId, choice: $choice) {
      txHash
    }
  }
`;

/**
 * ===========================================================================
 *  Helper hooks
 * ===========================================================================
 */

/**
 * Standardised error handler that pipes GraphQL errors
 * and network errors to a Chakra toast notification.
 */
const useErrorToast = () => {
  const toast = useToast();
  return useCallback(
    (title: string, error: ApolloError | Error) => {
      if (!error) return;
      const description =
        error instanceof ApolloError
          ? error.message || error.networkError?.message
          : error.message;
      toast({
        title,
        description,
        status: 'error',
        duration: 9000,
        isClosable: true,
        position: 'bottom-left',
      });
      // eslint-disable-next-line no-console
      console.error(title, error);
    },
    [toast],
  );
};

/**
 * ===========================================================================
 *  ShowPage Component
 * ===========================================================================
 */
const ShowPage: React.FC = () => {
  const { showId } = useParams<{ showId: string }>();
  const errorToast = useErrorToast();

  /**
   * -----------------------------------------------------------------------
   *  Queries & Subscriptions
   * -----------------------------------------------------------------------
   */
  const {
    data,
    loading: loadingShow,
    error: showError,
    refetch: refetchShow,
  } = useQuery(SHOW_DETAILS_QUERY, {
    variables: { id: showId },
    fetchPolicy: 'cache-and-network',
  });

  useEffect(() => {
    if (showError) errorToast('Unable to fetch show details', showError);
  }, [showError]);

  const { data: subData } = useSubscription(SHOW_EVENTS_SUBSCRIPTION, {
    variables: { showId },
    shouldResubscribe: true,
  });

  /**
   * -----------------------------------------------------------------------
   *  Mutations
   * -----------------------------------------------------------------------
   */
  const [mintPass, { loading: mintingPass }] = useMutation(MINT_PASS_MUTATION, {
    variables: { showId },
    onCompleted: () => {
      refetchShow();
      toast({
        title: 'Pass minted!',
        status: 'success',
        duration: 5000,
        isClosable: true,
      });
    },
    onError: err => errorToast('Pass minting failed', err),
  });

  const [stakePass, { loading: stakingPass }] = useMutation(
    STAKE_PASS_MUTATION,
    {
      onCompleted: () => {
        refetchShow();
        toast({
          title: 'Pass staked!',
          status: 'success',
          duration: 5000,
          isClosable: true,
        });
      },
      onError: err => errorToast('Staking failed', err),
    },
  );

  const [castVote, { loading: castingVote }] = useMutation(CAST_VOTE_MUTATION, {
    onCompleted: () => {
      refetchShow();
      toast({
        title: 'Vote submitted!',
        status: 'success',
        duration: 5000,
        isClosable: true,
      });
      voteModal.onClose();
    },
    onError: err => errorToast('Vote failed', err),
  });

  const toast = useToast();
  const voteModal = useDisclosure();

  /**
   * -----------------------------------------------------------------------
   *  Derived state & Memoised values
   * -----------------------------------------------------------------------
   */
  const show = data?.show;
  const { currentActId, currentProposal } = useMemo(() => {
    if (!subData?.showEvent) return {};
    const event = subData.showEvent;
    switch (event.__typename) {
      case 'ActStartedEvent':
        return { currentActId: event.actId };
      case 'VoteWindowOpenedEvent':
        return { currentProposal: event };
      default:
        return {};
    }
  }, [subData]);

  /**
   * -----------------------------------------------------------------------
   *  Handlers
   * -----------------------------------------------------------------------
   */
  const handleMintPass = () => mintPass();
  const handleStakePass = () => {
    if (!show?.userPass?.id) {
      return toast({
        title: 'No pass detected',
        description: 'Mint a pass before staking',
        status: 'warning',
        duration: 5000,
        isClosable: true,
      });
    }
    stakePass({ variables: { passId: show.userPass.id } });
  };

  const handleVote = (choice: string) => {
    if (!currentProposal) return;
    castVote({ variables: { proposalId: currentProposal.proposalId, choice } });
  };

  /**
   * -----------------------------------------------------------------------
   *  Render
   * -----------------------------------------------------------------------
   */
  if (loadingShow) {
    return (
      <Flex h="80vh" align="center" justify="center">
        <CircularProgress isIndeterminate size="120px" />
      </Flex>
    );
  }

  if (!show) {
    return (
      <Flex h="80vh" align="center" justify="center">
        <Heading size="lg">Show not found</Heading>
      </Flex>
    );
  }

  return (
    <Flex direction="column" w="full" px={8} py={6} gap={8}>
      {/* Header */}
      <ShowHeader show={show} />

      {/* Stage Canvas */}
      <Box h="400px" borderRadius="md" overflow="hidden" bg="black">
        <Canvas camera={{ position: [0, 5, 15], fov: 60 }}>
          <ambientLight intensity={0.6} />
          <pointLight position={[10, 10, 10]} />
          <Suspense fallback={null}>
            <StageScene currentActId={currentActId} />
          </Suspense>
          <OrbitControls enablePan={false} />
        </Canvas>
      </Box>

      {/* Controls */}
      <Flex direction={{ base: 'column', md: 'row' }} gap={6}>
        <PassPanel
          show={show}
          mintingPass={mintingPass}
          stakingPass={stakingPass}
          onMint={handleMintPass}
          onStake={handleStakePass}
        />
        <ActTimeline acts={show.acts} currentActId={currentActId} />

        {/* Live Vote */}
        {currentProposal && !show.userPass?.hasVoted && (
          <Button
            colorScheme="pink"
            onClick={voteModal.onOpen}
            isDisabled={castingVote}
            alignSelf="flex-start"
          >
            Cast Live Vote
          </Button>
        )}
      </Flex>

      <VoteModal
        isOpen={voteModal.isOpen}
        onClose={voteModal.onClose}
        proposal={currentProposal}
        onVote={handleVote}
        isSubmitting={castingVote}
      />
    </Flex>
  );
};

export default ShowPage;

/**
 * ===========================================================================
 *  Sub Components
 * ===========================================================================
 */

const ShowHeader: React.FC<{ show: any }> = ({ show }) => (
  <HStack align="flex-start" spacing={8}>
    <Box
      w={{ base: '120px', md: '180px' }}
      h={{ base: '120px', md: '180px' }}
      bgImage={`url(${show.coverImage})`}
      bgSize="cover"
      bgPos="center"
      borderRadius="md"
      boxShadow="lg"
      flexShrink={0}
    />
    <VStack align="flex-start" spacing={2}>
      <Heading>{show.title}</Heading>
      <Text color="gray.400">{show.description}</Text>
      <Text fontSize="sm" color="gray.500">
        Starts {new Date(show.startTime).toLocaleString()}
      </Text>
    </VStack>
  </HStack>
);

interface PassPanelProps {
  show: any;
  mintingPass: boolean;
  stakingPass: boolean;
  onMint: () => void;
  onStake: () => void;
}
const PassPanel: React.FC<PassPanelProps> = ({
  show,
  mintingPass,
  stakingPass,
  onMint,
  onStake,
}) => {
  const mintedPercentage =
    (show.mintedPassCount / show.totalPassSupply) * 100 || 0;

  return (
    <Flex
      direction="column"
      w={{ base: 'full', md: '280px' }}
      p={4}
      border="1px solid"
      borderColor="gray.700"
      borderRadius="md"
      bg="gray.900"
      gap={4}
    >
      <Heading size="sm">Your Pass</Heading>
      {show.userPass ? (
        <VStack align="flex-start" spacing={1}>
          <Text>ID: {show.userPass.id}</Text>
          <Text>Level: {show.userPass.level}</Text>
          <Text>Staked: {show.userPass.stakedBalance} SSC</Text>
        </VStack>
      ) : (
        <Text color="gray.500">You haven't minted a pass yet</Text>
      )}

      <VStack align="flex-start" w="full" spacing={2}>
        <Progress w="full" value={mintedPercentage} size="sm" />
        <Text fontSize="xs" color="gray.400">
          {show.mintedPassCount}/{show.totalPassSupply} minted
        </Text>
      </VStack>

      <Button
        colorScheme="cyan"
        onClick={onMint}
        isLoading={mintingPass}
        isDisabled={!!show.userPass}
      >
        {show.userPass ? 'Pass Minted' : 'Mint Pass'}
      </Button>

      <Button
        colorScheme="purple"
        variant="outline"
        onClick={onStake}
        isLoading={stakingPass}
        isDisabled={!show.userPass || !!show.userPass.stakedBalance}
      >
        {show.userPass?.stakedBalance ? 'Pass Staked' : 'Stake Pass'}
      </Button>
    </Flex>
  );
};

const ActTimeline: React.FC<{ acts: any[]; currentActId?: string }> = ({
  acts,
  currentActId,
}) => (
  <Flex
    direction="column"
    flex="1"
    p={4}
    border="1px solid"
    borderColor="gray.700"
    borderRadius="md"
    bg="gray.900"
    gap={3}
  >
    <Heading size="sm">Acts</Heading>
    {acts
      .sort((a, b) => a.order - b.order)
      .map(act => {
        const isActive = act.id === currentActId;
        return (
          <HStack key={act.id} spacing={2}>
            <Tooltip label={`${act.duration} mins`} placement="top">
              <Text
                fontWeight={isActive ? 'bold' : 'normal'}
                color={isActive ? 'cyan.400' : 'gray.200'}
              >
                {act.order}. {act.name}
              </Text>
            </Tooltip>
            {isActive && <TriangleDownIcon color="cyan.400" />}
          </HStack>
        );
      })}
  </Flex>
);

interface VoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  proposal: any;
  onVote: (choice: string) => void;
  isSubmitting: boolean;
}
const VoteModal: React.FC<VoteModalProps> = ({
  isOpen,
  onClose,
  proposal,
  onVote,
  isSubmitting,
}) => {
  if (!proposal) return null;

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="xl" isCentered>
      <ModalOverlay />
      <ModalContent bg="gray.800" border="1px solid" borderColor="gray.600">
        <ModalHeader>Live Vote</ModalHeader>
        <ModalBody>
          <VStack spacing={4}>
            {proposal.choices.map((c: string) => (
              <Button
                key={c}
                w="full"
                colorScheme="pink"
                variant="outline"
                onClick={() => onVote(c)}
                isLoading={isSubmitting}
                loadingText="Submitting"
              >
                {c}
              </Button>
            ))}
            <Button variant="ghost" onClick={onClose} w="full">
              Cancel
            </Button>
          </VStack>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

/**
 * ===========================================================================
 *  3D Stage Scene
 * ===========================================================================
 *
 *  NOTE: This is a placeholder ThreeJS scene that orbits around a
 *  color-coded stage to denote the current act. In production this
 *  would be replaced with an animated, performer-specific set piece.
 */
import { Suspense } from 'react';
import { MeshProps } from '@react-three/fiber';

const StageScene: React.FC<{ currentActId?: string }> = ({ currentActId }) => {
  const color = useMemo(() => {
    // Simple hashing of act id → color for variety
    if (!currentActId) return 'white';
    const code = currentActId
      .split('')
      .reduce((acc, c) => acc + c.charCodeAt(0), 0);
    return `hsl(${code % 360}, 80%, 50%)`;
  }, [currentActId]);

  return (
    <group>
      <StagePlane color={color} />
      <spotLight
        intensity={1.5}
        position={[0, 10, 0]}
        angle={0.3}
        penumbra={1}
        color={color}
      />
    </group>
  );
};

const StagePlane: React.FC<{ color: string } & MeshProps> = props => (
  <mesh rotation={[-Math.PI / 2, 0, 0]} {...props}>
    <circleBufferGeometry args={[5, 64]} />
    <meshStandardMaterial color={props.color} />
  </mesh>
);
```