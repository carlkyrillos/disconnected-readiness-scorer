# Disconnected Readiness Exception Process

## Purpose

Exceptions allow component teams to bypass specific disconnected readiness checks in extraordinary circumstances. They exist to unblock urgent work when a finding is either a false positive or represents a known limitation with a planned resolution.

Exceptions are **not** a mechanism to avoid disconnected compliance. They should be used sparingly and only when absolutely necessary. Every exception represents a potential failure in a disconnected customer environment — or at minimum, toil that must eventually be resolved.

## When to Request an Exception

An exception is appropriate when:

- The finding is a confirmed false positive that cannot be immediately fixed in the scanner rules
- The finding relates to a known issue with a tracked resolution timeline

An exception is **not** appropriate when:

- The team disagrees with the disconnected requirement itself
- The fix is straightforward but inconvenient
- The finding has been open for multiple sprints without progress

## Process

### Step 1: Identify the Blocker

Run the disconnected readiness scan (via PR check or manually) and identify the specific blocker-level finding that requires an exception.

Record the following:
- Rule name (e.g. `no-runtime-egress`, `no-image-tags`)
- File path flagged
- Finding message
- Why you believe this should be excepted

### Step 2: Create a JIRA Ticket

Clone the exception request template:

> **Template:** [RHOAIENG-XXXXX](https://issues.redhat.com/browse/RHOAIENG-XXXXX) *(placeholder — template TBD)*

The ticket must include:
- Summary: `Disconnected readiness exception: <brief description>`
- Component: the requesting team's component
- Description: the finding details from Step 1, the justification, and the proposed resolution timeline

### Step 3: Escalate for Approval

Work with your upline manager(s) to escalate the ticket to **Sherard Griffin** for review.

Sherard will evaluate:
- Is the justification valid?
- Is there a concrete plan to resolve the underlying issue?
- Is the resolution timeline acceptable?

### Step 4: Implement the Exception (After Approval Only)

Once Sherard approves the escalation and has commented such approval on the ticket, the component team may add the exception to their repo's `.disconnected-readiness/exceptions.yaml` file.

The exception **must** reference the approved JIRA ticket in the `reason` field:

```yaml
exceptions:
  - rule: no-runtime-egress
    path: "internal/client.go"
    reason: "Approved exception — calls cluster-internal API. See RHOAIENG-XXXXX"
```

### Step 5: Resolution and Removal

The vast majority of the time, the exception is temporary. The JIRA ticket tracks the resolution work. Once the underlying issue is fixed:

1. Remove the exception from `.disconnected-readiness/exceptions.yaml`
2. Verify the scan passes without the exception
3. Close the JIRA ticket

## Expectations

- Exceptions are reviewed on a regular cadence. Stale exceptions (open > 2 sprints) will be escalated.
- Teams are responsible for tracking and resolving their own exceptions.
- The number of active exceptions per component is visible on the Org Pulse dashboard.
