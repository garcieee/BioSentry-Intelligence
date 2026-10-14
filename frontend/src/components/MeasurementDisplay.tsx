import type { ReactElement } from "react";
import type { Measurement } from "../types";

type Primitive = string | number | boolean;

export interface MeasurementProps<T> {
  measurement: Measurement<T>;
  unit?: string;
}

function primitiveText(value: unknown): string {
  // A structured value stringifies to "[object Object]"; the overloads below make a missing
  // format() a compile error, and this makes it a loud failure instead of wrong text.
  if (typeof value === "object" && value !== null) {
    throw new Error("MeasurementDisplay: a structured value needs a format() function");
  }
  return String(value);
}

function Display<T>({
  measurement,
  unit,
  format,
}: MeasurementProps<T> & { format?: (value: T) => string }): ReactElement {
  const isNurse = measurement.provenance.source === "nurse";

  if (!measurement.data.present) {
    return <span className="missing">--</span>;
  }

  const formatted = format
    ? format(measurement.data.value)
    : primitiveText(measurement.data.value);

  return (
    <span className={isNurse ? "nurse-entered" : undefined}>
      {formatted}
      {unit && <span className="unit"> {unit}</span>}
      {isNurse && <sup className="prov-tag">N</sup>}
    </span>
  );
}

/**
 * Primitive values print as themselves; any other value type (blood pressure) must say how
 * it is written, or the call does not compile.
 */
export const MeasurementDisplay = Display as {
  <T extends Primitive>(props: MeasurementProps<T> & { format?: (value: T) => string }): ReactElement;
  <T>(props: MeasurementProps<T> & { format: (value: T) => string }): ReactElement;
};
