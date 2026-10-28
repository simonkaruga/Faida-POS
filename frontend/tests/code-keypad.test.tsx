import { cleanup, fireEvent, render } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CodeKeypad } from "../src/shared/CodeKeypad";

afterEach(cleanup);

function Harness({ onEnter, keyboard }: { onEnter?: () => void; keyboard?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <>
      <output>{value}</output>
      <CodeKeypad value={value} length={4} onChange={setValue} onEnter={onEnter} keyboard={keyboard} />
    </>
  );
}

const type = (...keys: string[]) => keys.forEach((key) => fireEvent.keyDown(window, { key }));

describe("M-Pesa code from a physical keyboard (counters without a touch screen)", () => {
  it("takes letters as capitals and digits, deletes, stops at the length, and Enter confirms", () => {
    const onEnter = vi.fn();
    const { container } = render(<Harness onEnter={onEnter} />);
    const typed = () => container.querySelector("output")!.textContent;
    type("p", "2", "q", "x", "Backspace", "m", "z");
    expect(typed()).toBe("P2QM");
    type("Enter");
    expect(onEnter).toHaveBeenCalledOnce();
  });

  it("can leave the keyboard to a number keypad on the same screen", () => {
    const { container } = render(<Harness keyboard={false} />);
    type("p", "2");
    expect(container.querySelector("output")!.textContent).toBe("");
  });
});
