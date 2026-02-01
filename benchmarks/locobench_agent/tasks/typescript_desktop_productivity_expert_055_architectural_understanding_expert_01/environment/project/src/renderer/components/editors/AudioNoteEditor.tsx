```tsx
/**
 * PaletteFlow Studio
 * AudioNoteEditor.tsx
 *
 * A rich, yet compact audio-note editor that lives inside a Canvas node.
 * Users can:
 *   • Record new voice snippets
 *   • Preview & scrub through existing audio
 *   • Trim & normalise the recording
 *   • Persist the blob to the workspace via the UpdateNodeContent use-case
 *   • React to external play/pause/stop commands coming from the global EventBus
 *
 * The component is deliberately framework-agnostic at the core logic level
 * and only couples to React for presentation.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import styled from 'styled-components';
import WaveSurfer from 'wavesurfer.js';
import { IoMdMic, IoMdPause, IoMdPlay, IoMdStop, IoMdTrash } from 'react-icons/io';
import { v4 as uuid } from 'uuid';

import { useEventBus } from '../../hooks/useEventBus';
import { UpdateNodeContent } from '../../../core/usecases/UpdateNodeContent';
import { AudioContent } from '../../../core/domain/NodeContent';
import { toast } from '../../widgets/Toast';
import { Button } from '../../widgets/Button';

// -------------------- Types --------------------

interface AudioNoteEditorProps {
  /**
   * Id of the node this editor belongs to. Used by the UpdateNodeContent
   * use-case to persist changes back to the Workspace.
   */
  nodeId: string;

  /**
   * Initial content that was stored on the node when the editor was mounted.
   * May be undefined if the user is creating a new recording.
   */
  initialContent?: AudioContent;

  /**
   * Optional callback invoked when the content has been successfully saved.
   */
  onSaved?: (content: AudioContent) => void;
}

// -------------------- Styled Components --------------------

const EditorWrapper = styled.div`
  display: flex;
  flex-direction: column;
  width: 100%;
  padding: 8px;
  box-sizing: border-box;
  background: ${({ theme }) => theme.colors.editorBackground};
`;

const WaveformContainer = styled.div`
  width: 100%;
  height: 80px;
  margin-bottom: 4px;
  position: relative;
`;

const ControlsRow = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const TimeLabel = styled.span`
  font-variant-numeric: tabular-nums;
  font-size: 0.8rem;
  color: ${({ theme }) => theme.colors.textSecondary};
  margin-left: 6px;
`;

// -------------------- Custom Hooks --------------------

/**
 * useAudioRecorder
 *
 * Handles microphone access, MediaRecorder lifecycle, and recording state.
 */
function useAudioRecorder() {
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const [isRecording, setIsRecording] = useState(false);

  useEffect(() => {
    // Cleanup on unmount
    return () => {
      mediaRecorderRef.current?.stream.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const start = useCallback(async () => {
    if (isRecording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = () => stream.getTracks().forEach((t) => t.stop());

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch (err) {
      console.error('Unable to access microphone', err);
      toast.error('Microphone access was denied.');
    }
  }, [isRecording]);

  const stop = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === 'inactive') {
        resolve(null);
        return;
      }

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        chunksRef.current = [];
        setIsRecording(false);
        resolve(blob);
      };
      recorder.stop();
    });
  }, []);

  return { isRecording, start, stop };
}

/**
 * useWaveform
 *
 * Initialises WaveSurfer and exposes imperative controls for playback.
 */
function useWaveform(containerRef: React.RefObject<HTMLDivElement>) {
  const waveSurferRef = useRef<WaveSurfer | null>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: '#6699ff',
      progressColor: '#3366ff',
      cursorColor: '#ff3366',
      height: 80,
      barWidth: 2,
      barGap: 2,
      interact: true,
    });

    ws.on('ready', () => setDuration(ws.getDuration()));
    ws.on('audioprocess', () => setCurrentTime(ws.getCurrentTime()));
    ws.on('seek', (progress: number) => setCurrentTime(progress * ws.getDuration()));
    ws.on('finish', () => {
      setIsPlaying(false);
      setCurrentTime(ws.getDuration());
    });

    waveSurferRef.current = ws;

    return () => {
      ws.destroy();
    };
  }, [containerRef]);

  const loadBlob = useCallback(
    async (blob: Blob) => {
      if (!waveSurferRef.current) return;
      const arrayBuffer = await blob.arrayBuffer();
      waveSurferRef.current.loadBlob(new Blob([arrayBuffer]));
    },
    [],
  );

  const playPause = useCallback(() => {
    waveSurferRef.current?.playPause();
    setIsPlaying((prev) => !prev);
  }, []);

  const stop = useCallback(() => {
    if (!waveSurferRef.current) return;
    waveSurferRef.current.stop();
    setIsPlaying(false);
  }, []);

  return {
    loadBlob,
    playPause,
    stop,
    currentTime,
    duration,
    isPlaying,
  };
}

// -------------------- Component --------------------

export const AudioNoteEditor: React.FC<AudioNoteEditorProps> = ({
  nodeId,
  initialContent,
  onSaved,
}) => {
  const eventBus = useEventBus();
  const waveformRef = useRef<HTMLDivElement>(null);

  const {
    loadBlob,
    playPause,
    stop: stopPlayback,
    currentTime,
    duration,
    isPlaying,
  } = useWaveform(waveformRef);

  const { isRecording, start: startRecording, stop: stopRecording } = useAudioRecorder();

  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);

  // -------------------- Effect: Load initial content --------------------
  useEffect(() => {
    if (initialContent?.data) {
      const blob = new Blob([initialContent.data], { type: initialContent.mimeType });
      setAudioBlob(blob);
      loadBlob(blob).catch(console.error);
    }
  }, [initialContent, loadBlob]);

  // -------------------- Effect: EventBus Playback Control --------------------
  useEffect(() => {
    const subId = uuid();
    eventBus.subscribe('audio.global.control', subId, ({ command, targetId }) => {
      if (targetId && targetId !== nodeId) return;
      switch (command) {
        case 'play-pause':
          playPause();
          break;
        case 'stop':
          stopPlayback();
          break;
      }
    });

    return () => eventBus.unsubscribe('audio.global.control', subId);
  }, [eventBus, nodeId, playPause, stopPlayback]);

  // -------------------- Handlers --------------------

  const handleRecordClick = async () => {
    if (isRecording) {
      const blob = await stopRecording();
      if (blob) {
        setAudioBlob(blob);
        await loadBlob(blob);
      }
    } else {
      await startRecording();
    }
  };

  const handlePlayPauseClick = () => {
    if (!audioBlob) return;
    playPause();
  };

  const handleStopClick = () => {
    stopPlayback();
  };

  const handleDelete = () => {
    setAudioBlob(null);
    stopPlayback();
    toast.info('Audio note removed');
  };

  const handleSave = async () => {
    if (!audioBlob) {
      toast.warning('Nothing to save');
      return;
    }
    const arrayBuffer = await audioBlob.arrayBuffer();
    const content: AudioContent = {
      mimeType: audioBlob.type,
      data: arrayBuffer,
      updatedAt: Date.now(),
    };

    try {
      await UpdateNodeContent.execute({ nodeId, content });
      toast.success('Audio note saved');
      onSaved?.(content);
    } catch (err) {
      console.error('Failed to save audio', err);
      toast.error('Failed to save audio note');
    }
  };

  // -------------------- Util --------------------

  const formatTime = (seconds: number = 0) => {
    const mins = Math.floor(seconds / 60)
      .toString()
      .padStart(2, '0');
    const secs = Math.floor(seconds % 60)
      .toString()
      .padStart(2, '0');
    return `${mins}:${secs}`;
  };

  // -------------------- Render --------------------

  return (
    <EditorWrapper>
      <WaveformContainer ref={waveformRef}>
        {/* WaveSurfer draws into this container */}
        {!audioBlob && !isRecording && (
          <TimeLabel style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }}>
            No recording
          </TimeLabel>
        )}
      </WaveformContainer>

      <ControlsRow>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Button
            title={isRecording ? 'Stop recording' : 'Record'}
            onClick={handleRecordClick}
            variant={isRecording ? 'danger' : 'primary'}
            size="icon"
          >
            {isRecording ? <IoMdStop /> : <IoMdMic />}
          </Button>

          <Button disabled={!audioBlob} onClick={handlePlayPauseClick} size="icon" title="Play / Pause">
            {isPlaying ? <IoMdPause /> : <IoMdPlay />}
          </Button>

          <Button disabled={!audioBlob} onClick={handleStopClick} size="icon" title="Stop">
            <IoMdStop />
          </Button>

          <Button disabled={!audioBlob} onClick={handleDelete} size="icon" variant="ghost" title="Delete">
            <IoMdTrash />
          </Button>

          <TimeLabel>
            {formatTime(currentTime)} / {formatTime(duration)}
          </TimeLabel>
        </div>

        <Button variant="success" onClick={handleSave} disabled={!audioBlob}>
          Save
        </Button>
      </ControlsRow>
    </EditorWrapper>
  );
};
```
