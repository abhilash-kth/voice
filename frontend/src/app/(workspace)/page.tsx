import AddFundsCard from "./billing/components/AddBalance";
import WalletStats from "./billing/components/WalletStats";
import StartCallCard from "./components/StartCallCard";

export default function Page() {
  return (
    <div className="space-y-4">
      <StartCallCard />
      <WalletStats />
      <AddFundsCard />
    </div>
  );
}
