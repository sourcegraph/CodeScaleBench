```tsx
/* PaletteFlow Studio – Renderer Layer
 * -----------------------------------
 * Renders a semantic link (edge) between two canvas nodes.
 * A link is visualised as an SVG cubic-bezier curve with an
 * arrow-head marker.  The component is fully interactive:
 *   • shows hover/selection states
 *   • supports right-click context menu
 *   • reacts to theme + zoom changes
 *
 * The implementation purposefully lives in the renderer layer,
 * keeping the core domain entity (Link) entirely framework-agnostic.
 */

import React, {
  memo,
  useMemo,
  useCallback,
  MouseEvent,
  CSSProperties,
} from 'react';
import { useSelector } from 'react-redux';
import { useTheme } from '@mui/material/styles';
import { RootState } from '../../state/store';
import { CanvasZoomSelector } from '../../state/selectors/canvasSelectors';
import { LinkModel } from '../../../domain/entities/Link';
import { Vector2 } from '../../../domain/common/Vector2';
import { clamp } from '../../utils/math';
import { useCanvasDispatch } from '../../state/hooks/useCanvasDispatch';

/* ---------- Types & Props ------------------------------------------------ */
interface LinkComponentProps {
  link: LinkModel;

  /** Method for retrieving the current (absolute) position of a node */
  getNodeCenter: (nodeId: string) => Vector2 | null;

  /** Allows higher-order components to indicate selection */
  isSelected?: boolean;

  /** Optional override to capture click */
  onSelect?: (linkId: string, e: MouseEvent<SVGPathElement>) => void;

  /** Context-menu callback */
  onContextMenu?: (linkId: string, e: MouseEvent<SVGPathElement>) => void;
}

/* ---------- Constants ---------------------------------------------------- */
const HITBOX_STROKE_PX = 12; // Invisible stroke used for hit-testing
const ARROW_MARKER_ID = 'paletteflow-link-arrow';

/* ---------- Utility Functions ------------------------------------------- */

/**
 * Creates a smooth cubic-bezier path between two points.
 * The control point distance is proportional to the distance
 * between the points but clamped for short links to avoid over-shoot.
 */
function buildBezierPath(
  from: Vector2,
  to: Vector2,
  curvature = 0.3
): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const distance = Math.sqrt(dx * dx + dy * dy);

  // Determine control points
  const cpOffset = clamp(distance * curvature, 40, 300);
  const cp1 = { x: from.x + cpOffset, y: from.y };
  const cp2 = { x: to.x - cpOffset, y: to.y };

  return `M ${from.x},${from.y} C ${cp1.x},${cp1.y} ${cp2.x},${cp2.y} ${to.x},${to.y}`;
}

/* ---------- Component ---------------------------------------------------- */
const LinkComponent: React.FC<LinkComponentProps> = ({
  link,
  getNodeCenter,
  isSelected = false,
  onSelect,
  onContextMenu,
}) => {
  /* ----- External state ----- */
  const theme = useTheme();
  const zoom = useSelector((state: RootState) => CanvasZoomSelector(state));
  const dispatch = useCanvasDispatch();

  /* ----- Derived geometry ----- */
  const { pathString, midPoint } = useMemo(() => {
    const from = getNodeCenter(link.sourceNodeId);
    const to = getNodeCenter(link.targetNodeId);

    if (!from || !to) {
      return { pathString: '', midPoint: { x: 0, y: 0 } };
    }

    const pathStr = buildBezierPath(from, to, link.curvature ?? 0.25);

    // Mid-point for label / interaction feedback
    const mid = {
      x: (from.x + to.x) / 2,
      y: (from.y + to.y) / 2,
    };

    return { pathString: pathStr, midPoint: mid };
  }, [
    getNodeCenter,
    link.sourceNodeId,
    link.targetNodeId,
    link.curvature,
  ]);

  /* ----- Interaction Handlers ----- */
  const handleClick = useCallback(
    (e: MouseEvent<SVGPathElement>) => {
      e.stopPropagation();
      if (onSelect) {
        onSelect(link.id, e);
      } else {
        dispatch.canvas.selectLink(link.id);
      }
    },
    [dispatch, link.id, onSelect]
  );

  const handleContextMenu = useCallback(
    (e: MouseEvent<SVGPathElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (onContextMenu) {
        onContextMenu(link.id, e);
      } else {
        dispatch.canvas.openLinkContextMenu(link.id, {
          x: e.clientX,
          y: e.clientY,
        });
      }
    },
    [dispatch, link.id, onContextMenu]
  );

  /* ----- Styling ----- */
  const strokeColor = isSelected
    ? theme.palette.primary.main
    : theme.palette.text.secondary;

  const strokeWidth = useMemo<number>(
    () => (isSelected ? 2.3 / zoom : 1.6 / zoom),
    [isSelected, zoom]
  );

  const style: CSSProperties = useMemo(
    () => ({
      vectorEffect: 'non-scaling-stroke', // keep width independent of zoom
      cursor: 'pointer',
      transition: 'stroke 120ms ease',
    }),
    []
  );

  /* ----- Early render guard ----- */
  if (!pathString) return null;

  /* ----- Render ----- */
  return (
    <>
      {/* Hitbox (invisible) */}
      <path
        d={pathString}
        stroke="transparent"
        strokeWidth={HITBOX_STROKE_PX / zoom}
        fill="none"
        onClick={handleClick}
        onContextMenu={handleContextMenu}
      />

      {/* Visible Edge */}
      <path
        d={pathString}
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        fill="none"
        markerEnd={`url(#${ARROW_MARKER_ID})`}
        style={style}
      />

      {/* Label (optional debug of weight/distance etc.) */}
      {link.label && (
        <text
          x={midPoint.x}
          y={midPoint.y - 4 / zoom}
          fontSize={`${10 / zoom}px`}
          textAnchor="middle"
          fill={theme.palette.text.disabled}
          pointerEvents="none"
        >
          {link.label}
        </text>
      )}
    </>
  );
};

export default memo(LinkComponent);

/* ---------- Marker Definition ------------------------------------------- */
/**
 * LinkMarkerDefs provides the SVG <defs> required by LinkComponent.
 * It should be mounted once inside the canvas’ main <svg>.
 */
export const LinkMarkerDefs = () => {
  const theme = useTheme();
  return (
    <defs>
      <marker
        id={ARROW_MARKER_ID}
        viewBox="0 0 10 10"
        refX="8"
        refY="5"
        markerWidth="5"
        markerHeight="5"
        orient="auto-start-reverse"
      >
        <path d="M 0 0 L 10 5 L 0 10 z" fill={theme.palette.text.secondary} />
      </marker>
    </defs>
  );
};
```
