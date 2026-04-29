export const getServices = async (initData, tenantId) => {
  const response = await fetch('http://localhost:8000/api/get_services', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      init_data: initData,
      tenant_id: tenantId,
    }),
  });

  if (!response.ok) {
    throw new Error('Network response was not ok');
  }

  return response.json();
};