// ABOUTME: Sprint 6 — banner shown on the category edit page when component weights don't sum to 100%.
// ABOUTME: Scoring normalizes at runtime; the banner just tells admins their config drifted.
import { Alert } from "../ui/Alert";

interface Props {
  total: number;
}

export function ComponentWeightWarning({ total }: Props) {
  return (
    <Alert tone="warning" title="Component weights don't sum to 100%">
      Current total is {total.toFixed(2)}%. Scoring will normalize at runtime,
      but the resulting weights may not match your intent. Adjust the components
      so their active weights sum to 100.
    </Alert>
  );
}
