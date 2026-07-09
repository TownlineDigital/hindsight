export default function CoachingFlags({ flags }) {
  if (!flags || !flags.length) {
    return <div className="card empty">No coaching flags yet.</div>;
  }
  return (
    <ul className="flags">
      {flags.map((f, i) => (
        <li key={i}>{f}</li>
      ))}
    </ul>
  );
}
