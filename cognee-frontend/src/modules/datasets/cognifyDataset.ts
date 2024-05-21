export default function cognifyDataset(dataset: { id: string }) {
  return fetch('http://0.0.0.0:8000/cognify', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      datasets: [dataset.id],
    }),
  }).then((response) => response.json());
}
