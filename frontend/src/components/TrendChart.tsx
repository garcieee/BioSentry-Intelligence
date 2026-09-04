interface DataPoint {
  time: string;
  value: number;
}

interface Props {
  data: DataPoint[];
  label: string;
  unit: string;
  width?: number;
  height?: number;
  responsive?: boolean;
  color?: string;
  warningHigh?: number;
  warningLow?: number;
}

export function TrendChart({
  data,
  label,
  unit,
  width = 400,
  height = 140,
  responsive = true,
  color = "var(--ink)",
  warningHigh,
  warningLow,
}: Props) {
  if (data.length < 2) return null;

  const values = data.map((d) => d.value);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const min = Math.min(dataMin, warningLow ?? dataMin) * 0.95;
  const max = Math.max(dataMax, warningHigh ?? dataMax) * 1.05;
  const range = max - min || 1;

  const padL = 40;
  const padR = 24;
  const padT = 8;
  const padB = 24;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const points = data.map((d, i) => {
    const x = padL + (i / (data.length - 1)) * plotW;
    const y = padT + plotH - ((d.value - min) / range) * plotH;
    return { x, y, ...d };
  });

  const linePath = `M${points.map((p) => `${p.x},${p.y}`).join("L")}`;
  const fillPath = `${linePath}L${points[points.length - 1].x},${padT + plotH}L${points[0].x},${padT + plotH}Z`;

  // Y-axis ticks
  const ticks = 3;
  const yTicks = Array.from({ length: ticks }, (_, i) => {
    const val = min + (range * i) / (ticks - 1);
    const y = padT + plotH - (i / (ticks - 1)) * plotH;
    return { val: Math.round(val), y };
  });

  // X-axis labels (first, middle, last)
  const xLabels = [0, Math.floor(data.length / 2), data.length - 1].map(
    (i) => ({
      label: data[i].time,
      x: points[i].x,
    }),
  );

  return (
    <div style={{ position: "relative" }}>
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: "10px",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--label)",
          marginBottom: "4px",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>{label}</span>
        <span>
          {values[values.length - 1]} {unit}
        </span>
      </div>
      <svg
        width={responsive ? "100%" : width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        {/* Grid lines */}
        {yTicks.map((t) => (
          <line
            key={t.val}
            x1={padL}
            y1={t.y}
            x2={width - padR}
            y2={t.y}
            stroke="var(--border)"
            strokeWidth={0.5}
          />
        ))}

        {/* Warning thresholds */}
        {warningHigh !== undefined && (() => {
          const y = padT + plotH - ((warningHigh - min) / range) * plotH;
          return (
            <>
              <line
                x1={padL} y1={y} x2={width - padR} y2={y}
                stroke="#c0392b" strokeWidth={1} strokeDasharray="6,4" opacity={0.5}
              />
              <text x={width - padR + 2} y={y + 3} fontSize={8} fill="#c0392b" fontFamily="var(--font-sans)" opacity={0.7}>
                {warningHigh}
              </text>
            </>
          );
        })()}
        {warningLow !== undefined && (() => {
          const y = padT + plotH - ((warningLow - min) / range) * plotH;
          return (
            <>
              <line
                x1={padL} y1={y} x2={width - padR} y2={y}
                stroke="#c0392b" strokeWidth={1} strokeDasharray="6,4" opacity={0.5}
              />
              <text x={width - padR + 2} y={y + 3} fontSize={8} fill="#c0392b" fontFamily="var(--font-sans)" opacity={0.7}>
                {warningLow}
              </text>
            </>
          );
        })()}

        {/* Fill */}
        <path d={fillPath} fill={color} opacity={0.06} />

        {/* Line */}
        <path
          d={linePath}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Current dot with pulse */}
        <circle
          cx={points[points.length - 1].x}
          cy={points[points.length - 1].y}
          r={3}
          fill={color}
        >
          <animate
            attributeName="r"
            values="3;5;3"
            dur="2s"
            repeatCount="indefinite"
          />
          <animate
            attributeName="opacity"
            values="1;0.5;1"
            dur="2s"
            repeatCount="indefinite"
          />
        </circle>

        {/* Y labels */}
        {yTicks.map((t) => (
          <text
            key={t.val}
            x={padL - 6}
            y={t.y + 3}
            textAnchor="end"
            fontSize={10}
            fill="var(--label)"
            fontFamily="var(--font-sans)"
          >
            {t.val}
          </text>
        ))}

        {/* X labels */}
        {xLabels.map((l) => (
          <text
            key={l.label}
            x={l.x}
            y={height - 4}
            textAnchor="middle"
            fontSize={9}
            fill="var(--label)"
            fontFamily="var(--font-sans)"
          >
            {l.label}
          </text>
        ))}
      </svg>
    </div>
  );
}
