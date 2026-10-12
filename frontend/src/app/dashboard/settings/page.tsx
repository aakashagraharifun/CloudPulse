"use client";

import { DetectionSettingsForm } from "@/components/features/settings/detection-settings";
import { AllocationRules } from "@/components/features/settings/allocation-rules";
import { NotificationChannels } from "@/components/features/settings/notification-channels";
import { PageHeader } from "@/components/ui/primitives";

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="Detection thresholds, where alerts are delivered, and how untagged costs are attributed."
      />
      <nav aria-label="Settings sections" className="mb-4 flex flex-wrap gap-2 text-sm">
        <a href="#detection" className="rounded-md bg-white px-3 py-1.5 font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50">Anomaly detection</a>
        <a href="#notifications" className="rounded-md bg-white px-3 py-1.5 font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50">Notifications</a>
        <a href="#allocation" className="rounded-md bg-white px-3 py-1.5 font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50">Cost allocation</a>
      </nav>
      <div className="space-y-6">
        <div id="detection" className="scroll-mt-20">
          <DetectionSettingsForm />
        </div>
        <div id="notifications" className="scroll-mt-20">
          <NotificationChannels />
        </div>
        <div id="allocation" className="scroll-mt-20">
          <AllocationRules />
        </div>
      </div>
    </>
  );
}
