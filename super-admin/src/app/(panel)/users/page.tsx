import { Suspense } from "react";
import UsersTable from "./componenets/users-table";
import { StateBox } from "@/components/StateBox";

export default function Page() {
  return (
    <Suspense
      fallback={
        <StateBox loading={true} error={null} empty={null}>
          <div className="min-h-[420px]" />
        </StateBox>
      }
    >
      <UsersTable />
    </Suspense>
  );
}
