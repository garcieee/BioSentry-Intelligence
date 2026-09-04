import type { Measurement } from "../types";

interface Props<T> {
  measurement: Measurement<T>;
  unit?: string;
  format?: (value: T) => string;
}

export function MeasurementDisplay<T>({
  measurement,
  unit,
  format,
}: Props<T>) {
  const isNurse = measurement.provenance.source === "nurse";

  if (!measurement.data.present) {
    return <span className="missing">--</span>;
  }

  const formatted = format
    ? format(measurement.data.value)
    : String(measurement.data.value);

  return (
    <span className={isNurse ? "nurse-entered" : undefined}>
      {formatted}
      {unit && <span className="unit"> {unit}</span>}
      {isNurse && <sup className="prov-tag">N</sup>}
    </span>
  );
}
