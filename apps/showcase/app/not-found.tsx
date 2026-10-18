import { ButtonLink, PageHeader } from '@/components/index.ts'

export default function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" subtitle="This page is not part of the showcase." />
      <ButtonLink href="/" variant="primary" icon="arrow-right">Back to the start</ButtonLink>
    </>
  )
}
