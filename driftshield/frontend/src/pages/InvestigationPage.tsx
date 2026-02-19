import { useParams } from 'react-router-dom'

export function InvestigationPage() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold mb-4">Investigation: {id}</h2>
      <p className="text-muted-foreground">Investigation view will go here.</p>
    </div>
  )
}
