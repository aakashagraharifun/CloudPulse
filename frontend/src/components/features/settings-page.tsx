"use client";

import { AccountSettings } from "@/components/features/settings/account";
import { AllocationRules } from "@/components/features/settings/allocation-rules";
import { AuditLog } from "@/components/features/settings/audit-log";
import { DetectionSettingsForm } from "@/components/features/settings/detection-settings";
import { NotificationChannels } from "@/components/features/settings/notification-channels";
import { UserManagement } from "@/components/features/settings/users";
import { useAuth } from "@/components/shell/auth";
import { Notice, PageHeader } from "@/components/ui/primitives";

const LINK =
  "rounded-md bg-white px-3 py-1.5 font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50";

export default function SettingsPage() {
  const { can } = useAuth();
  const admin = can("admin");
  return (
    <>
      <PageHeader
        title="Settings"
        description="Detection thresholds, where alerts are delivered, and how untagged costs are attributed."
      />
      <nav aria-label="Settings sections" className="mb-4 flex flex-wrap gap-2 text-sm">
        <a href="#account" className={LINK}>Account</a>
        <a href="#detection" className={LINK}>Anomaly detection</a>
        <a href="#notifications" className={LINK}>Notifications</a>
        <a href="#allocation" className={LINK}>Cost allocation</a>
        {admin && <a href="#users" className={LINK}>Users</a>}
        {admin && <a href="#audit" className={LINK}>Audit log</a>}
      </nav>
      {!admin && (
        <div className="mb-4">
          <Notice tone="info">Only admins can change workspace settings. You can change your own password.</Notice>
        </div>
      )}
      <div className="space-y-6">
        <div id="account" className="scroll-mt-20">
          <AccountSettings />
        </div>
        <div id="detection" className="scroll-mt-20">
          <DetectionSettingsForm />
        </div>
        <div id="notifications" className="scroll-mt-20">
          <NotificationChannels />
        </div>
        <div id="allocation" className="scroll-mt-20">
          <AllocationRules />
        </div>
        {admin && (
          <div id="users" className="scroll-mt-20">
            <UserManagement />
          </div>
        )}
        {admin && (
          <div id="audit" className="scroll-mt-20">
            <AuditLog />
          </div>
        )}
      </div>
    </>
  );
}
